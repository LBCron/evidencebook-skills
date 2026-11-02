"""scripts/calibration_claims.py: the week's calibration summaries and ratings cited in a window Result."""
import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from calibration_claims import add_calibration_claims, calibration_records, week_start  # noqa: E402
from calibration_summary import URN as SUMMARY_URN  # noqa: E402
from human_rating import URN as RATING_URN  # noqa: E402
from result_v0 import headline_from_result  # noqa: E402

PIN = "aa" * 32
SUMMARY_PREFIX = f"{SUMMARY_URN}:contract:"


def cite(digest):
    return {"digest_alg": "SHA-256", "digest": digest}


def requirement_claim(case, report):
    evidence = [cite(report)]
    return {"id": f"{case}::c1", "contract_ref": "contract@1", "requirement_ref": "c1", "tier": "judged",
            "grade": "self-attested", "sufficiency": "SATISFIED", "verdict": "met", "evidence": evidence,
            "proofs": [], "presentation": {"kind": "disclosure", "status": "SATISFIED", "evidence": evidence}}


def window_result(*reports):
    claims = [requirement_claim(f"case{i}", r) for i, r in enumerate(reports)]
    return {"result_version": "evidence-result-v0", "generated_at": "2026-10-31T23:59:59Z", "claims": claims,
            "aggregate": {"coverage": {"evaluated_population": len(claims), "excluded_not_applicable": 0,
                                       "unknown_count": 0},
                          "buckets": {"met": [c["id"] for c in claims], "not_met": [], "not_evaluable": []}},
            "view": {"spec_version": "presentation/v1", "title": "t"}}


def summary_body(week, pin=PIN):
    return {"record_version": "calibration-summary/v1", "record_id": f"{SUMMARY_URN}:contract:{week}:{pin[:16]}",
            "computed_at": "2026-10-11T23:59:59Z", "judge_pin": {"digest": pin}}


def rating_body(case, week, report):
    return {"record_version": "human-rating/v1", "record_id": f"{RATING_URN}:{case}:{week}",
            "case": {"digest": report}}


class WeekStart(unittest.TestCase):
    def test_monday_of_the_iso_week(self):
        self.assertEqual(week_start("week:2026-W41"), datetime.date(2026, 10, 5))

    def test_not_a_week_key(self):
        self.assertIsNone(week_start("day:2026-10-05"))
        self.assertIsNone(week_start("week:2026-W99"))


class Records(unittest.TestCase):
    def test_keeps_this_contracts_summaries_under_the_pin_and_every_rating(self):
        bodies = [("s1", summary_body("week:2026-W41")),
                  ("s-other-pin", summary_body("week:2026-W41", "bb" * 32)),
                  ("s-other-contract", {**summary_body("week:2026-W41"), "record_id": f"{SUMMARY_URN}:other:week:2026-W41:aa"}),
                  ("r1", rating_body("conv:task-1:trial-0", "week:2026-W41", "rep1")),
                  ("x", {"record_version": "evaluation-report/v1"}), ("y", None)]
        got = calibration_records(bodies, SUMMARY_PREFIX, PIN)
        self.assertEqual([s["capsule_id"] for s in got["summaries"]], ["s1"])
        self.assertEqual(got["ratings"], [{"capsule_id": "r1", "week": "week:2026-W41", "case_digest": "rep1"}])


class Claims(unittest.TestCase):
    def records(self):
        return calibration_records([
            ("s41", summary_body("week:2026-W41")), ("s42", {**summary_body("week:2026-W42"), "computed_at": "2026-10-18T23:59:59Z"}),
            ("s45", {**summary_body("week:2026-W45"), "computed_at": "2026-11-08T23:59:59Z"}),
            ("r-in", rating_body("a", "week:2026-W41", "rep1")),
            ("r-uncited", rating_body("b", "week:2026-W41", "rep-not-in-result")),
            ("r-other-week", rating_body("c", "week:2026-W42", "rep1")),
        ], SUMMARY_PREFIX, PIN)

    def test_one_claim_per_week_citing_the_summary_then_the_weeks_cited_ratings(self):
        doc = window_result("rep1", "rep2")
        added = add_calibration_claims(doc, self.records(), datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertEqual(added, 2)  # W41 and W42; W45 starts Nov 2, outside the window
        w41, w42 = doc["claims"][-2:]
        self.assertEqual([e["digest"] for e in w41["evidence"]], ["s41", "r-in"])
        self.assertEqual([e["digest"] for e in w42["evidence"]], ["s42", "r-other-week"])
        for claim in (w41, w42):
            self.assertEqual(claim["type"], "calibration")
            self.assertEqual(claim["contract_ref"], "contract-calibration@1")
            self.assertEqual(claim["presentation"]["evidence"], claim["evidence"])
        self.assertEqual(w41["id"], "calibration-2026-W41-s41")

    def test_aggregate_counts_the_claims(self):
        doc = window_result("rep1")
        add_calibration_claims(doc, self.records(), datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertEqual(doc["aggregate"]["coverage"]["evaluated_population"], 3)
        self.assertEqual(len(doc["aggregate"]["buckets"]["not_evaluable"]), 2)

    def test_a_week_with_no_summary_has_no_claim(self):
        records = calibration_records([("r", rating_body("a", "week:2026-W41", "rep1"))], SUMMARY_PREFIX, PIN)
        doc = window_result("rep1")
        self.assertEqual(add_calibration_claims(doc, records, datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)), 0)
        self.assertEqual(len(doc["claims"]), 1)

    def test_a_week_straddling_the_window_edge_counts(self):
        doc = window_result("rep1")
        # W41 is Oct 5-11; a window that ends on Oct 5 still overlaps it, one that ends Oct 4 does not.
        self.assertEqual(add_calibration_claims(doc, self.records(), datetime.date(2026, 9, 1), datetime.date(2026, 10, 5)), 1)
        doc = window_result("rep1")
        self.assertEqual(add_calibration_claims(doc, self.records(), datetime.date(2026, 9, 1), datetime.date(2026, 10, 4)), 0)

    def test_headline_ignores_calibration_claims(self):
        doc = window_result("rep1")
        before = headline_from_result(doc)
        add_calibration_claims(doc, self.records(), datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertEqual(headline_from_result(doc), before)


if __name__ == "__main__":
    unittest.main()
