"""Answer service questions using locator records and dated announcements."""
from datetime import date, datetime
import re

from contract import Answer, Source
from products import SITE, unavailable

CONTACT = "/contact"
JOIN = "/about/join"
NEWS = "/newsroom/"
STUDENT = "/personal/loans/student-loans"
DASH = r"[-–—]"
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def plain(text):
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").strip()


def publication(page):
    match = re.search(rf"^{MONTH} \d{{1,2}}, \d{{4}}$", page.markdown, re.M)
    return datetime.strptime(match[0], "%B %d, %Y").date() if match else date.min


def answer_member(query, pages, snapshot_id, cutoff):
    def page_at(path):
        return pages.get(SITE + path)

    def evidence(page, quote=None):
        return Source(page.url, snapshot_id, quote)

    def extract(page, pattern):
        if page:
            return next((line for line in page.markdown.splitlines()
                         if re.search(pattern, line, re.I)), None)
        return None

    def news(slug):
        return sorted((page for url, page in pages.items() if url.startswith(SITE + NEWS + slug)),
                      key=publication, reverse=True)

    contact = page_at(CONTACT)
    if re.search(r"\b(routing|aba) (?:transit )?(?:number|code)\b", query):
        line = extract(contact, r"routing number.{0,5}\d{9}")
        if line:
            number = re.search(r"\b\d{9}\b", line)[0]
            cash = page_at("/business/cash-management")
            sources = [evidence(contact, line)]
            cash_line = extract(cash, rf"(?:routing|aba) number.*{number}")
            if cash_line:
                sources.append(evidence(cash, cash_line))
            return Answer(f"Dupaco's routing number is {number}.", sources)

    if contact and ("locator" in query or re.search(r"\b(?:find|locate|nearest|closest)\b.*\b(?:branch|atm)\b", query)):
        return Answer(f"Use Dupaco's branch and ATM locator at {contact.url}.", [evidence(contact)])

    if re.search(r"\b(?:join|become a .*member|membership eligibility|eligible.*member|qualify.*membership)\b", query):
        join = page_at(JOIN)
        if join:
            if re.search(r"\b(eligible|eligibility|qualify|who)\b", query):
                conditions = [plain(line).lstrip("- ") for line in join.markdown.splitlines()
                              if re.match(r"- You (live or work|have an immediate family|belong)", line)]
                states = extract(join, r"Iowa, Illinois and Wisconsin")
                if conditions:
                    text = "You can join if any of these applies: " + " ".join(conditions)
                    if states:
                        text += " Dupaco serves communities in Iowa, Illinois and Wisconsin."
                    return Answer(text, [evidence(join, " ".join(conditions))])
            link = re.search(r"\]\((https://join\.dupaco\.com/)\)", join.markdown)
            if link:
                return Answer(f"Apply online for Dupaco membership at {link[1]}.", [evidence(join, link[0])])

    if re.search(r"\b(?:update|change)\b.*\b(?:contact (?:information|details|info)|mailing address|phone number)\b", query):
        line = extract(contact, r"contact us.*Shine.*tel:")
        if line:
            phone = re.search(r"\[([\d-]+)\]\(tel:", line)
            if phone:
                return Answer(f"For help updating your information, use Contact Us in Shine or call {phone[1]}.",
                              [evidence(contact, line)])

    if re.search(r"\b(?:mobile wallet|mobile payments?|apple pay|google pay|samsung pay)\b", query):
        shine = page_at("/shine")
        line = extract(shine, r"You can add your Dupaco .*cards to.*Pay")
        if line:
            return Answer(plain(line), [evidence(shine, line)])

    if re.search(r"\b(?:student|college|university|education)\b", query) and re.search(r"\b(?:loan[s]?|financ\w*|refinanc\w*)\b", query):
        student = page_at(STUDENT)
        if student:
            if re.search(r"\b(?:rate|apr)\b", query):
                return unavailable("I can't verify a student loan rate in the snapshot. Check Dupaco's student loan page for its rate link.", evidence(student))
            lines = [extract(student, pattern) for pattern in
                     (r"need to fill the funding gap", r"^Defer full payments", r"origination fees")]
            lines = [line for line in lines if line]
            if lines:
                return Answer("Dupaco offers student loans and refinancing. " + " ".join(map(plain, lines)),
                              [evidence(student, line) for line in lines])

    if re.search(r"\bhome(?:\$tart|\s*start)\b", query):
        for article in news("first-time-homebuyers"):
            line = extract(article, r"Home\$tart program.*\$[\d,]+")
            if line:
                return Answer(plain(line), [evidence(article, line)])

    if "forbes" in query:
        for article in news("forbes-ranks-dupaco-as-a-top-credit-union"):
            line = extract(article, r"forbes.*(?:top-rated credit unions|best.in.state)")
            if line:
                return Answer(plain(line), [evidence(article, line)])

    if "volunteer time off" in query or re.search(r"\bvto\b", query):
        years = re.findall(r"\b20\d{2}\b", query)
        expected = int(years[0]) if years else cutoff.year - 1 if "last year" in query else None
        latest = None
        for article in news("volunteering-pays-off"):
            line = extract(article, r"\d+ Dupaco employees.*used.*Volunteer Time Off")
            if line:
                report_year = re.search(r"\bin (\d{4})\b", line)
                if latest is None:
                    latest = (article, line)
                if expected is None or (report_year and int(report_year[1]) == expected):
                    return Answer(plain(line).lstrip("- "), [evidence(article, line)])
        if latest and expected is not None:
            article, line = latest
            return unavailable(f"I couldn't verify the count for {expected}. Latest published count I found: "
                               + plain(line).lstrip("- "), evidence(article, line))

    if re.search(r"\bhy[- ]?vee\b", query):
        for article in news("dupaco-evolves-with-purpose"):
            if re.search(r"\b(?:full.service|where|alternativ\w*|other branches)\b", query):
                line = extract(article, r"same services at Dupaco full-service branches")
                if line:
                    match = re.search(r"full-service branches at ([^”]+)", line)
                    if match:
                        return Answer("The closure notice directs members to " + match[1], [evidence(article, line)])
            else:
                line = extract(article, rf"will close {MONTH} \d{{1,2}}, \d{{4}}")
                if line:
                    closing = re.search(rf"{MONTH} \d{{1,2}}, \d{{4}}", line)[0]
                    closed = cutoff >= datetime.strptime(closing, "%B %d, %Y").date()
                    status = "The branch was scheduled to close on" if closed else "The branch is scheduled to close on"
                    return Answer(f"{status} {closing}, according to Dupaco's closure notice.", [evidence(article, line)])

    if re.search(r"\b(?:how many|number of)\b.*\b(?:branches|branch offices|locations)\b", query):
        for article in news(""):
            line = extract(article, r"\b\d+ branch office locations\b")
            if line:
                count = re.search(r"\b\d+ branch office locations\b", line)[0]
                published = publication(article)
                return Answer(f"Dupaco reported {count} in {published.strftime('%B %Y')}.",
                              [evidence(article, line)])

    if contact and re.search(r"\b(address|where is|located)\b", query):
        records = re.findall(r"(?m)^Dupaco Branch\s*\n\s*([^\n]+)", contact.markdown)
        matches = []
        for address in records:
            parts = address.split(",")
            if len(parts) >= 3 and re.search(r"\b" + re.escape(parts[1].strip().lower()) + r"\b", query):
                matches.append(address)
        if matches:
            addresses = [re.sub(r"\bLn\.", "Lane", address) for address in matches]
            return Answer("Dupaco branch addresses: " + "; ".join(addresses) + ".",
                          [evidence(contact, address) for address in matches])

    if re.search(r"\b(?:hours|when.*(?:open|close))\b", query):
        drive = bool(re.search(r"\bdrive[- ]?(?:up|through|thru)\b", query))
        if drive or re.search(r"\b(?:lobby|branch(?:es)?)\b", query):
            return branch_hours(query, drive, contact, news, evidence)
    return None


def branch_hours(query, drive, contact, news, evidence):
    schedules = []
    for slug, location in (
        ("dupaco-celebrates-completion-of-newest-learning-lab", "Cedar Rapids Learning Lab"),
        ("dupaco-community-credit-union-celebrates-completion-of-expanded-branch", "Platteville"),
        ("dupaco-community-credit-union-celebrates-mineral-point-branch", "Mineral Point Road"),
    ):
        for page in news(slug):
            heading = r"Drive[- ]up" if drive else "Lobby"
            match = re.search(rf"^\*\*{heading}\*\*[ \t]*([\s\S]+?)(?=^\*\*|^###|\Z)",
                              page.markdown, re.I | re.M)
            if not match:
                continue
            days = re.findall(r"^(?:Monday|Friday|Saturday|Sunday)[^\n]+", match[1].strip(), re.M)
            if days:
                schedules.append((location, ", ".join(days), evidence(page, "\n".join(days))))
                break
    specific = re.search(r"\b(?:for|at|of) (?:the |dupaco's )?(.+?) branch\b", query)
    matching = [(name, hours, source) for name, hours, source in schedules if name.lower() in query]
    if matching:
        schedules = matching
    elif specific or re.search(r"\b(?:mullan|galena|hy[- ]vee)\b", query):
        return unavailable("I can't verify hours for that branch. Please check Dupaco's branch locator.",
                           *([evidence(contact)] if contact else []))
    if not schedules:
        return unavailable("I can't verify published branch hours for this snapshot.")
    label = "Drive-up" if drive else "Lobby"
    text = f"{label} hours vary by branch. Published examples:\n"
    text += "\n".join(f"{name}: {hours}." for name, hours, _ in schedules)
    sources = [source for _, _, source in schedules]
    if contact:
        text += "\nCheck the branch locator for the exact location and current hours."
        sources.append(evidence(contact))
    return Answer(text, sources)
