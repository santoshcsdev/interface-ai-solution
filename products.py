"""Read published rates from the dedicated product pages."""
import re
from decimal import Decimal

from contract import Answer, Source

SITE = "https://www.dupaco.com"
HOME = "/personal/loans/home-loans"
SAVINGS = "/personal/savings-account"
CHECKING = "/personal/checking-accounts"
PERSONAL_LOANS = "/personal/loans/personal-loans"
CARDS = "/personal/credit-cards"
BUSINESS_CARDS = "/business/credit-cards"
PERCENT = r"\d+(?:\.\d+)?%"
MONEY = r"\$([\d,]+(?:\.\d+)?)([kKmM]?)"


def money(text):
    return [Decimal(amount.replace(",", "")) * {"": 1, "k": 1000, "m": 1000000}[suffix.lower()]
            for amount, suffix in re.findall(MONEY, text)]


def table_rows(page):
    for line in page.markdown.splitlines():
        if line.startswith("|"):
            yield line, [cell.strip() for cell in line.strip("|").split("|")]


def unavailable(text, *sources):
    return Answer(text=text, sources=list(sources), confident=False)


def answer_products(query, pages, snapshot_id, conflicts):
    def source(path, quote=None):
        return Source(SITE + path, snapshot_id, quote)

    def rows(path):
        page = pages.get(SITE + path)
        return table_rows(page) if page else ()

    def render(entries, intro=""):
        if not entries:
            return unavailable("I can't verify a published rate for that product and tier.")
        citations = []
        for _, evidence in entries:
            for item in evidence if isinstance(evidence, list) else [evidence]:
                if item not in citations:
                    citations.append(item)
        return Answer(intro + "\n".join(text for text, _ in entries), citations)

    rate_query = re.search(r"\b(rate[s]?|aprs?|apy|interest|dividend|yield)\b", query)
    if rate_query and re.search(r"\b(construction loans?|adjustable[- ]rate mortgages?|arms?)\b", query):
        if SITE + HOME in pages:
            return unavailable("I couldn't find a published rate for that loan. Please contact Dupaco's mortgage team.",
                               source(HOME))
        return unavailable("I can't verify a published rate for that loan.")

    equity = re.search(r"\b(?:heloc|home equity (?:line(?: of credit)?|loan))\b", query)
    if rate_query and equity:
        path = "/personal/loans/home-equity"
        is_line = equity[0] != "home equity loan"
        introductory = bool(re.search(r"\b(?:intro\w*|promotional)\b", query))
        term = re.search(r"\b(\d+)\s*[- ]?\s*months?\b", query)
        entries = []
        for line, cells in rows(path):
            if len(cells) != 2:
                continue
            product, value = cells
            apr = re.match(PERCENT, value)
            if not apr:
                continue
            if is_line:
                if introductory and product == "HELOC Intro Rate":
                    published = re.match(r".*?will apply\.", value)
                    if published:
                        entries.append((f"HELOC: {published[0]}", source(path, line)))
                elif not introductory and product in {
                    "Home Equity Line of Credit (HELOC)", "HELOC – Standard",
                }:
                    entries.append((f"Standard HELOC: variable APR as low as {apr[0]}, subject to qualification.",
                                    source(path, line)))
            elif not introductory:
                fixed_term = re.fullmatch(r"Loan [–-] Standard \((\d+) mo\)", product)
                if fixed_term and (not term or term[1] == fixed_term[1]):
                    entries.append((f"{fixed_term[1]}-month fixed home equity loan: as low as {apr[0]} APR.",
                                    source(path, line)))
        return render(entries)

    if rate_query and re.search(r"\b(mortgages?|home loan[s]?)\b", query):
        if re.search(r"\b(jumbo|fha|va|heloc|usda|reverse|interest-only)\b", query):
            return unavailable("I can't verify a published rate for that mortgage program.")
        years = re.search(r"\b(\d+)\s*[- ]?\s*years?\b", query)
        program = "Refinance" if re.search(r"\brefinanc\w*", query) else "Purchase"
        selected = {}
        for line, cells in rows(HOME):
            if len(cells) != 5:
                continue
            name, rate, _, apr, _ = cells
            term = re.match(rf"{program}: (\d+)-Year Fixed Conventional\b", name, re.I)
            if not term or not re.fullmatch(PERCENT, rate) or not re.fullmatch(PERCENT, apr):
                continue
            if years and term[1] != years[1]:
                continue
            limits = money(name)
            original = source(HOME + "#rates", line)
            rate_source = apr_source = original
            for conflict in conflicts:
                if conflict.sources[-1].quote != line or conflict.resolution == conflict.values[-1]:
                    continue
                if conflict.topic.endswith(" mortgage APR"):
                    apr, apr_source = conflict.resolution, conflict.sources[0]
                elif conflict.topic.endswith(" mortgage interest rate"):
                    rate, rate_source = conflict.resolution, conflict.sources[0]
            citations = [rate_source] if rate_source == apr_source else [rate_source, apr_source]
            selected.setdefault((int(term[1]), limits[0] if limits else None),
                                (f"{name}: {rate} interest rate, {apr} APR.", citations))

        amounts = money(query)
        if amounts:
            if len(set(amounts)) != 1 or amounts[0] <= 0:
                return unavailable("I need one loan amount to identify the published mortgage tier.")
            amount = amounts[0]
            by_term = {}
            for (term, limit), entry in sorted(selected.items(), key=lambda item: item[0][1] or 0):
                if limit is not None and limit >= amount:
                    by_term.setdefault(term, entry)
            return render(list(by_term.values()))
        return render([entry for _, entry in sorted(
            selected.items(), key=lambda item: (-item[0][0], item[0][1] or 0))])

    if rate_query and re.search(r"\bpersonal loans?\b", query):
        months = re.search(r"\b(\d+)\s*[- ]?\s*months?\b", query)
        entries = []
        for line, cells in rows(PERSONAL_LOANS):
            if len(cells) != 2:
                continue
            term = re.fullmatch(r"(\d+)\s+Months?", cells[0], re.I)
            apr = re.match(PERCENT, cells[1])
            if term and apr and (not months or months[1] == term[1]):
                entries.append((f"{term[1]}-month personal loan: as low as {apr[0]} APR.",
                                source(PERSONAL_LOANS, line)))
        return render(entries)

    card_query = re.search(r"\b(?:credit cards?|platinum visa|rewards visa)\b", query)
    if rate_query and card_query:
        entries = []
        names = re.findall(r"\b(platinum|rewards)\b", query)
        introductory = re.search(r"\b(intro\w*|balance transfer)\b", query)
        page = pages.get(SITE + CARDS)
        if page and "business" not in query:
            name = None
            for line in page.markdown.splitlines():
                heading = re.match(r"^#+\s+(.+)", line)
                if heading:
                    name = heading[1] if heading[1] in {"Platinum Visa", "Rewards Visa"} else None
                if not name or (names and name.split()[0].lower() not in names):
                    continue
                if introductory:
                    if "intro APR" in line:
                        entries.append((re.sub(r"\[(\d+)\]\([^)]+\)", "", line.lstrip("- ")),
                                        source(CARDS, line)))
                else:
                    apr = re.search(rf"{PERCENT}\s*[-–]\s*{PERCENT}\s+APR", line)
                    if apr and "intro" not in line.lower():
                        entries.append((f"{name}: {apr[0]} standard.", source(CARDS, line)))
        if not introductory and ("business" in query or (not names and "personal" not in query)):
            for line, cells in rows(BUSINESS_CARDS):
                if len(cells) == 2 and re.fullmatch(r"Business (Platinum|Rewards) Visa", cells[0]):
                    apr = re.match(PERCENT, cells[1])
                    if apr and (not names or cells[0].split()[1].lower() in names):
                        entries.append((f"{cells[0]}: {apr[0]} variable APR.", source(BUSINESS_CARDS, line)))
        return render(entries)

    if not rate_query:
        return None
    business = "business" in query
    products = (
        "Share Savings", "Bright Savings", "Free Checking", "1st Rate Checking",
        "You Name It Savings", "High-Yield Savings", "Holiday Club Savings",
        "Launchpad Savings", "Health Savings Account", "Investor's Choice Money Market",
    )
    names = {name for name in products if name.lower() in query}
    if not names and re.search(r"\bchecking\b", query):
        names = {"Free Checking", "1st Rate Checking"}
    comparison = re.search(r"\b(?:any|highest|maximum|top)\b", query)
    if not names and comparison and "savings" in query:
        names = {"Share Savings"}
    if not names:
        return None
    entries = []
    amounts = money(query)
    requested_apy = re.search(PERCENT, query) if "apy" in query else None
    paths = ("/business/savings-accounts", "/business/checking-accounts") if business else (SAVINGS, CHECKING)
    for path in paths:
        for line, cells in rows(path):
            if len(cells) != 6 or cells[0].removeprefix("Business ").removesuffix(" (Business)") not in names:
                continue
            name, tier, dividend, apy, _, _ = cells
            dividend, apy = re.match(PERCENT, dividend), re.match(PERCENT, apy)
            if not dividend or not apy:
                continue
            bounds = money(tier)
            if amounts and bounds and not all(
                amount >= bounds[0] and (len(bounds) == 1 or amount <= bounds[1]) for amount in amounts
            ):
                continue
            label = name if tier in {"—", "-", "None"} else f"{name} ({tier})"
            entries.append((Decimal(apy[0][:-1]), f"{label}: {dividend[0]} dividend rate, {apy[0]} APY.",
                            source(path, line)))
    if entries and requested_apy:
        target = Decimal(requested_apy[0][:-1])
        matches = [entry for entry in entries if entry[0] == target]
        if matches:
            return render([(text, evidence) for _, text, evidence in matches], "Yes. ")
        _, text, evidence = max(entries, key=lambda entry: entry[0])
        return render([(text, evidence)], "The requested APY isn't listed for these tiers. Highest listed: ")
    if entries and comparison:
        entries = [max(entries, key=lambda entry: entry[0])]
    return render([(text, evidence) for _, text, evidence in entries])
