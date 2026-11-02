"""The week's calibration records, cited by a roll-up Result as `calibration` claims.

A Result of type-`calibration` claims (evidence-result-v0 section 4.1) cites exactly one
calibration-summary/v1 record and otherwise only human-rating/v1 records, one claim per
summary. This module reads those records out of the book (scripts/rollup_day.py) and adds
the claims to a merged window Result (scripts/merge_results.py).

Which ratings a claim cites is the reading AAC's outcome-report reader makes: a rating
binds to the requirement claim that cites the report it rated, so a claim cites the
week's ratings whose `case.digest` is a report some requirement claim of the Result
cites, and no others. A summary is cited when its week overlaps the Result's window and
it calibrates the pin the roll-up is scoped to; a week with no summary has no claim.

The claim's contract_ref is its own, `<pack>-calibration@1`: a report built against the
pack's contract (evidencebook `report.Build` with a contract) refuses a claim that cites
a requirement the contract does not have, and the pack contract has no calibration
requirement, while it skips a claim of another contract_ref.

The claim's verdict is `not_evaluable` with sufficiency GAP: the Evidence Contract
defines no rule that says what agreement meets a requirement (the spec leaves it to the
contract, and a verdict is never a ratio of the summary's counts), so the claim reports
the calibration by citation and does not pretend to decide it. The counts stay in the
summary record.
"""
import datetime
import re

from result_v0 import _digest_ref

SUMMARY = "calibration-summary/v1"
RATING = "human-rating/v1"
CLAIM_TYPE = "calibration"
REQUIREMENT_REF = "agreement"

_WEEK = re.compile(r"week:(\d{4})-W(\d{2})")


def week_start(week_key):
    """The Monday of 'week:YYYY-Www' (run_weekly.py's key), or None for any other text."""
    m = _WEEK.fullmatch(week_key)
    if m is None:
        return None
    try:
        return datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def _week_of(record_id):
    """The 'week:YYYY-Www' a weekly record_id names (a rating's ends with it, a summary's
    is followed by the pin's digest prefix)."""
    m = re.search(r"week:\d{4}-W\d{2}", record_id or "")
    return m.group(0) if m else None


def calibration_records(capsule_bodies, summary_prefix, expected_pin=None):
    """JSON-ready {"summaries": [...], "ratings": [...]} from (capsule_id, body) pairs: the
    weekly calibration-summary/v1 records whose record_id starts with `summary_prefix`
    (scripts/calibration_summary.py's URN and the contract) and, when `expected_pin` is
    given, calibrate that pin, and every human-rating/v1 record. Each names its week from
    its record_id; a record whose week cannot be read is left out."""
    summaries, ratings = [], []
    for capsule_id, body in capsule_bodies:
        if not isinstance(body, dict):
            continue
        week = _week_of(body.get("record_id"))
        if week is None:
            continue
        if body.get("record_version") == SUMMARY and body["record_id"].startswith(summary_prefix):
            pin = (body.get("judge_pin") or {}).get("digest")
            if expected_pin is None or pin == expected_pin:
                summaries.append({"capsule_id": capsule_id, "week": week, "computed_at": body.get("computed_at", "")})
        elif body.get("record_version") == RATING:
            case = (body.get("case") or {}).get("digest")
            if case:
                ratings.append({"capsule_id": capsule_id, "week": week, "case_digest": case})
    return {"summaries": sorted(summaries, key=lambda s: (s["computed_at"], s["capsule_id"])),
            "ratings": sorted(ratings, key=lambda r: r["capsule_id"])}


def add_calibration_claims(document, records, first_day, last_day):
    """Append one calibration claim per summary in `records` whose week overlaps
    first_day..last_day (datetime.date) to `document` (a merged Result v0), citing the
    summary then the week's ratings of the reports the document's requirement claims cite.
    Updates aggregate buckets and coverage; returns the number of claims added."""
    cited = {e["digest"] for c in document["claims"] if c.get("type") in (None, "requirement") for e in c["evidence"]}
    contract_ref = document["claims"][0]["contract_ref"].rpartition("@")[0] + "-calibration@1"
    added = 0
    for summary in records["summaries"]:
        monday = week_start(summary["week"])
        if monday is None or monday > last_day or monday + datetime.timedelta(days=6) < first_day:
            continue
        digests = [summary["capsule_id"]] + sorted({
            r["capsule_id"] for r in records["ratings"]
            if r["week"] == summary["week"] and r["case_digest"] in cited})
        evidence = [_digest_ref(d) for d in digests]
        claim = {
            "id": f"calibration-{summary['week'].removeprefix('week:')}-{summary['capsule_id'][:16]}",
            "type": CLAIM_TYPE,
            "contract_ref": contract_ref,
            "requirement_ref": REQUIREMENT_REF,
            "tier": "recomputed",
            "grade": "self-attested",
            "sufficiency": "GAP",
            "verdict": "not_evaluable",
            "evidence": evidence,
            "proofs": [],
            "presentation": {"kind": "disclosure", "status": "INSUFFICIENT", "evidence": evidence},
        }
        document["claims"].append(claim)
        document["aggregate"]["buckets"]["not_evaluable"].append(claim["id"])
        added += 1
    document["aggregate"]["coverage"]["evaluated_population"] += added
    return added
