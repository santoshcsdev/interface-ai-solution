"""Compare corresponding rows from known copies of published rate tables."""
from datetime import date, datetime
from decimal import Decimal
import re
from typing import NamedTuple

from contract import Conflict, Source
from products import CHECKING, HOME, PERCENT, SAVINGS, SITE

TABLE = re.compile(r"(?m)(?:^\|[^\n]+\|[ \t]*\n?)+")
EFFECTIVE = re.compile(r"rates are effective as of (\d{1,2}/\d{1,2}/\d{4})", re.I)


class Rate(NamedTuple):
    value: str
    effective: date
    source: Source


def extract_rates(page, snapshot_id, family):
    """Key rows by product, tier and measure. Keep the first main mortgage table."""
    result = {}
    for table in TABLE.finditer(page.markdown):
        effective = EFFECTIVE.search(page.markdown[table.end():].lstrip()[:90])
        day = datetime.strptime(effective[1], "%m/%d/%Y").date() if effective else date.min
        lines = table[0].splitlines()
        header = lines[0].lower()
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            topic = cells[0]
            if family == "mortgage" and len(cells) == 5 and re.match(
                    r"(Purchase|Refinance): \d+-Year Fixed Conventional\b", topic):
                fields = (("interest rate", cells[1]), ("APR", cells[3]))
            elif family != "mortgage" and len(cells) == 6 and "dividend rate" in header:
                topic = f"{topic} ({cells[1]})"
                fields = (("dividend rate", cells[2]), ("APY", cells[3]))
            elif family != "mortgage" and len(cells) == 4 and "dividend rate" in header and (
                    "certificate" in topic.lower() or re.fullmatch(r"\d+ Month", topic, re.I)):
                if re.fullmatch(r"\d+ Month", topic, re.I):
                    topic += " Regular Certificate"
                topic += f" ({cells[3]} minimum)"
                fields = (("dividend rate", cells[1]), ("APY", cells[2]))
            else:
                continue
            if family == "business deposits" and not topic.startswith("Business "):
                topic = "Business " + topic
            if family == "mortgage":
                topic += " mortgage"
            key = re.sub(r"(?<=\d)\.00\b", "", topic.lower().replace("–", "-").replace(",", ""))
            for measure, cell in fields:
                value = re.match(PERCENT, cell)
                if value:
                    result.setdefault((key, measure),
                                      (topic, Rate(value[0], day, Source(page.url, snapshot_id, line))))
    return result


def rate_conflicts(pages, snapshot_id):
    comparisons = (
        (HOME, ("/rates", "/homebuying-guidance"), "mortgage"),
        (SAVINGS, ("/rates",), "personal deposits"),
        (CHECKING, ("/rates",), "personal deposits"),
        ("/business/savings-accounts", ("/business-rates",), "business deposits"),
        ("/business/checking-accounts", ("/business-rates",), "business deposits"),
    )
    for primary, copies, family in comparisons:
        page = pages.get(SITE + primary)
        if not page:
            continue
        canonical = extract_rates(page, snapshot_id, family)
        for path in copies:
            mirror = pages.get(SITE + path)
            if not mirror:
                continue
            comparison = extract_rates(mirror, snapshot_id, family)
            for key, (topic, official) in canonical.items():
                if key not in comparison:
                    continue
                other = comparison[key][1]
                if Decimal(official.value[:-1]) == Decimal(other.value[:-1]):
                    continue
                newer = max((official, other), key=lambda rate: rate.effective)
                if official.effective == other.effective:
                    reason = "The dedicated product rate table takes precedence when the effective dates tie."
                elif min(official.effective, other.effective) == date.min:
                    reason = f"Only one table gives an effective date ({newer.effective.isoformat()})."
                else:
                    reason = f"The {newer.effective.isoformat()} effective rate supersedes the older table."
                yield Conflict(f"{topic} {key[1]}", [other.value, official.value],
                               [other.source, official.source], newer.value, reason)
