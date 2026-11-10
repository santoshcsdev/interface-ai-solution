# Dupaco snapshot knowledge system

Run from the supplied participant kit using Python 3.11:

```sh
python3.11 harness/run_eval.py --submission ../interface-ai-solution --eval eval/public_eval.jsonl
```

The evaluator supplies the contract and data. The solution uses the Python
standard library. It requires no API keys, paid services, or network access.

Each answer selects the latest complete snapshot on or before `as_of`.
With no explicit cutoff, the system recognizes dates in the question such
as “as of 2026-05-31” or “in May 2026.” Otherwise it selects the newest
ingested snapshot. Citations carry
the snapshot ID and usually quote the exact evidence. Rate questions use
the relevant product tables. Certificate terms and tiers, loan model years
and terms, and mortgage purpose and amount determine the applicable row.
APR, APY, interest rate, and dividend rate are tracked separately. General
mortgage questions show the conventional purchase schedule with the
lowest amount tier first. Home equity answers distinguish standard and
introductory HELOC APRs from fixed loan APRs. Advertised rates are subject
to qualification.

The official auto table takes precedence over the affordability calculator.
Other rate comparisons cover corresponding rows in dedicated mortgage,
savings, and checking pages and their known rate table copies. Published
effective dates determine the winner, with the dedicated product page
breaking ties. An auto conflict requires the same term and overlapping
model years. Other comparisons require matching product, tier, and measure.
Repeated disagreements retain the newest snapshot showing the pair.
Successive updates to the same rate table are treated as history.

Service questions use the locator, product help pages, and dated newsroom
announcements. Branch hours from announcements are labeled as published
examples. Volunteer counts are tied to the year the source reports.
The system abstains when the topic or qualifier cannot be verified.
Coverage depends on the supported product families and source formats.
Conflict detection covers the recognized rate table families and sources.
