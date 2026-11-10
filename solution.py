from calendar import monthrange
from collections import defaultdict
from datetime import date as calendar_date, datetime
import re
from typing import NamedTuple

from contract import Answer, Conflict, Snapshot, Source
from member_info import answer_member
from products import answer_products
from rate_conflicts import rate_conflicts


HISTORICAL_DATE = re.compile(
    r"\b(?:as of|on)\s+(\d{4}-\d{2}-\d{2})\b"
    r"|\b(?:as of|back in|in)\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(?:(\d{1,2}),?\s+)?(\d{4})\b"
)


def question_date(query):
    match = HISTORICAL_DATE.search(query)
    if not match:
        return None, query
    iso, month, day, year = match.groups()
    if iso:
        cutoff = calendar_date.fromisoformat(iso)
    else:
        month_number = datetime.strptime(month, "%B").month
        year_number = int(year)
        cutoff = calendar_date(year_number, month_number,
                               int(day) if day else monthrange(year_number, month_number)[1])
    # Date tokens are evidence cutoffs and should not also select a product tier.
    return cutoff.isoformat(), query[:match.start()] + " " + query[match.end():]


class Certificate(NamedTuple):
    name: str
    months: int
    special: bool
    jumbo: bool
    dividend: str
    apy: str
    minimum: str
    source: Source


def certificate_rows(snapshot, business):
    path = "/business/savings-accounts" if business else "/personal/savings-account"
    for page in snapshot.pages:
        if page.url.rstrip("/") != "https://www.dupaco.com" + path:
            continue
        columns = None
        for line in page.markdown.splitlines():
            if not line.startswith("|"):
                columns = None
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 4:
                columns = None
                continue
            name, dividend, apy, minimum = cells
            if name.lower() in {"certificate", "term"} and "Dividend Rate" in dividend:
                columns = cells
                continue
            term = re.match(r"(\d+)\s*[- ]?\s*month\b", name, re.I)
            if not columns or not term:
                continue
            regular = bool(re.fullmatch(r"\d+\s+Month", name, re.I))
            special = "certificate" in name.lower() and "special" in name.lower()
            if not (regular or special):
                continue
            if regular:
                name += " Regular Certificate"
            rate = re.match(r"\d+(?:\.\d+)?%", dividend)
            yield_rate = re.match(r"\d+(?:\.\d+)?%", apy)
            if rate and yield_rate and re.fullmatch(r"\$[\d,]+(?:\.\d{2})?", minimum):
                yield Certificate(
                    name, int(term[1]), special, "jumbo" in name.lower(), rate[0], yield_rate[0],
                    minimum.removesuffix(".00"), Source(page.url, snapshot.snapshot_id, line),
                )


AUTO_RATE_URL = "https://www.dupaco.com/personal/loans/auto-motorcycle-loans"
AUTO_CALCULATOR_URL = "https://www.dupaco.com/calculators/vehicle-affordability"
AUTO_REASON = "The official auto loan rate table takes precedence over the affordability calculator."
AUTO_ROW = re.compile(
    r"^\|\s*(?P<first>\d{4})(?:[-–](?P<last>\d{2}|\d{4}))? Model Year"
    r"(?P<older> \(and older\))?\s*\|\s*(?P<months>\d+)\s+Months"
    r"\s*\|\s*(?P<apr>\d+(?:\.\d+)?%)\s+APR\d*\s*\|\s*$",
    re.I | re.M,
)


class AutoRate(NamedTuple):
    first_year: int
    last_year: int
    months: int
    apr: str
    source: Source

    def applies(self, year, months):
        return self.months == months and self.first_year <= year <= self.last_year


def year_label(first, last):
    if first == 0:
        return f"{last} and older"
    return str(first) if first == last else f"{first}–{last}"


def auto_rates(snapshot):
    official, calculator = [], []
    for page in snapshot.pages:
        url = page.url.rstrip("/")
        if url not in {AUTO_RATE_URL, AUTO_CALCULATOR_URL}:
            continue
        target = official if url == AUTO_RATE_URL else calculator
        for row in AUTO_ROW.finditer(page.markdown):
            first = int(row["first"])
            end = row["last"]
            last = first if end is None else int(end) + (first // 100 * 100 if len(end) == 2 else 0)
            target.append(AutoRate(
                0 if row["older"] else first, last, int(row["months"]), row["apr"],
                Source(page.url, snapshot.snapshot_id, row[0].strip()),
            ))
    return official, calculator


def auto_conflicts(official, calculator):
    for rate in official:
        for other in calculator:
            first = max(rate.first_year, other.first_year)
            last = min(rate.last_year, other.last_year)
            if rate.months != other.months or first > last or rate.apr == other.apr:
                continue
            yield Conflict(
                topic=f"{rate.months}-month auto loan APR ({year_label(first, last)} model years)",
                values=[other.apr, rate.apr],
                sources=[other.source, rate.source],
                resolution=rate.apr,
                reason=AUTO_REASON,
            )


class Knowledge:
    def __init__(self):
        self.auto = {}
        self.pages = {}
        self.snapshot_ids = {}
        self.rate_disagreements = {}
        self.certificates = {}

    def _date(self, as_of):
        return max((date for date in self.pages if as_of is None or date <= as_of), default=None)

    def ingest(self, snapshot: Snapshot) -> None:
        self.auto[snapshot.taken_on] = auto_rates(snapshot)
        self.pages[snapshot.taken_on] = {page.url.rstrip("/"): page for page in snapshot.pages}
        self.snapshot_ids[snapshot.taken_on] = snapshot.snapshot_id
        self.rate_disagreements[snapshot.taken_on] = list(
            rate_conflicts(self.pages[snapshot.taken_on], snapshot.snapshot_id)
        )
        for business in (False, True):
            index = defaultdict(list)
            for offer in certificate_rows(snapshot, business):
                index[offer.months].append(offer)
            self.certificates[snapshot.taken_on, business] = index

    def answer(self, question, as_of=None):
        query = re.sub(r"[‐‑–—−]", "-", question.lower()).replace("’", "'")
        try:
            inferred_date, rate_query = question_date(query)
            cutoff = as_of or inferred_date
            if cutoff is not None:
                cutoff = calendar_date.fromisoformat(cutoff).isoformat()
        except ValueError:
            return Answer(text="I couldn't identify a valid date for that question.", confident=False)
        date = self._date(cutoff)
        if date is None:
            return Answer(text="I don't have a snapshot for that date.", confident=False)
        term = re.search(r"\b(\d+)\s*[- ]?\s*months?\b", query)
        pages = self.pages[date]
        snapshot_id = self.snapshot_ids[date]
        if re.search(r"\b(certificates?|cds?)\b", query):
            business = "business" in query
            if re.search(r"\b(link|url|where.*(?:find|see))\b", query):
                url = ("https://www.dupaco.com/business/savings-accounts" if business else
                       "https://www.dupaco.com/personal/savings-account#rates")
                if url.split("#")[0] in pages:
                    return Answer(f"Certificate rates: {url}", [Source(url, snapshot_id)])
            if term or re.search(r"\b(rate[s]?|apy|yield)\b", query):
                index = self.certificates[date, business]
                offers = index.get(int(term[1]), []) if term else [row for rows in index.values() for row in rows]
                if "special" in query:
                    offers = [offer for offer in offers if offer.special]
                if "regular" in query:
                    offers = [offer for offer in offers if not offer.special]
                if "jumbo" in query or "standard" in query:
                    offers = [offer for offer in offers if offer.jumbo == ("jumbo" in query)]
                if not offers:
                    return Answer(text="I can't verify that certificate offer.", confident=False)
                offers = sorted(offers, key=lambda offer: (offer.months, offer.special, offer.jumbo))
                dividend = bool(re.search(r"\bdividend\s+rate\b", query))
                text = "\n".join(
                    f"{offer.name}: {offer.dividend + ' dividend rate' if dividend else offer.apy + ' APY'} "
                    f"({offer.minimum} minimum)"
                    for offer in offers
                )
                return Answer(text=text, sources=[offer.source for offer in offers])
        product = answer_products(rate_query, pages, snapshot_id, self.rate_disagreements[date])
        if product is not None:
            notes = {
                conflict.reason for conflict in self.rate_disagreements[date]
                if conflict.reason and any(source.quote and source.quote == candidate.quote
                                           and source.url.split("#")[0].rstrip("/") == candidate.url.rstrip("/")
                                           for source in product.sources for candidate in conflict.sources)
            }
            if notes:
                product.conflict_note = " ".join(sorted(notes))
            return product
        # A concrete model year selects the tier even when its boundaries have moved.
        if (re.search(r"\b(auto|car|vehicle)\b", query)
                and re.search(r"\b(loan|financ\w*|apr)\b", query)
                and re.search(r"\b(apr|rate|annual percentage rate)\b", query)
                and not re.search(r"\b(mini[- ]?max|fleet|business|commercial|refinanc\w*)\b", query)):
            years = set(re.findall(r"\b(?:19|20)\d{2}\b", rate_query))
            terms = set(re.findall(r"\b(\d+)\s*[- ]?\s*months?\b", query))
            if len(years) == len(terms) == 1:
                return self._auto_answer(date, int(years.pop()), int(terms.pop()))
            return Answer(text="I need the vehicle model year and loan term to identify the APR.",
                          confident=False)
        member = answer_member(query, pages, snapshot_id, calendar_date.fromisoformat(cutoff or date))
        if member is not None:
            return member
        return Answer(text="I can't verify that from the available Dupaco information. Please contact Dupaco.",
                      confident=False)

    def _auto_answer(self, date, year, months):
        official, calculator = self.auto[date]
        candidates = [rate for rate in official if rate.applies(year, months)]
        if len(candidates) != 1:
            return Answer(text="I can't verify an official APR for that model year and term.",
                          confident=False)
        rate = candidates[0]
        tier = year_label(rate.first_year, rate.last_year)
        disputed = any(other.applies(year, months) and other.apr != rate.apr
                       for other in calculator)
        return Answer(
            text=f"The {months}-month auto loan APR is as low as {rate.apr} "
                 f"for the {tier} model-year tier, subject to qualification.",
            sources=[rate.source],
            conflict_note=AUTO_REASON if disputed else None,
        )

    def conflicts(self):
        # Collapse unchanged disagreements across crawls, keeping the newest citations.
        distinct = {}
        for date in sorted(self.auto):
            for conflict in [*auto_conflicts(*self.auto[date]), *self.rate_disagreements[date]]:
                distinct[conflict.topic, tuple(conflict.values)] = conflict
        return list(distinct.values())


def build():
    return Knowledge()
