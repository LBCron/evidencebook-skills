"""The clause report is not the AAC Judge Record Family's evaluation-report/v1
(evidencebook-skills#113): the name it seals, and how a reader treats the
legacy name.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "judges"))

from clause_report import CLAUSE_REPORT, LEGACY_CLAUSE_REPORT, is_clause_report  # noqa: E402
from rollup_day import _in_scope, case_tiers, report_determinations  # noqa: E402
from run_daily import build_report  # noqa: E402
from run_weekly import week_frame  # noqa: E402

CLAUSE = {"id": "c.one", "tier": "judged", "claim": "No change the fare class forbids."}
ANSWER = {"verdict": "met", "rationale": "ok"}
# The member names every JF evaluation-report/v1 carries (schemas/judge/evaluation-report-v1.json).
JF_REQUIRED = {"record_version", "record_id", "epistemic_type", "generated_at", "contract_ref", "judge_pin", "cases"}
JF_NAMES = {"evaluation-report/v1", "contract-compile/v1", "adjudication/v1", "close/v1", "sample-manifest/v1",
            "human-rating/v1", "calibration-summary/v1"}
JF_SHAPED = {"record_version": "evaluation-report/v1", "record_id": "er-1", "epistemic_type": "semantic_judgment",
             "generated_at": "2026-11-03T00:00:00Z", "contract_ref": "ec:x@1", "judge_pin": {},
             "cases": [{"case_id": "k", "verdict": "met", "acts": [], "method": {}}]}


class EmittedRecord(unittest.TestCase):
    def test_build_report_seals_the_clause_report_name(self):
        report = build_report(CLAUSE, {}, ANSWER, "contract/v1", "case-1", "cap-1", "pin-abc", "2026-11-03")
        self.assertEqual(report["record_type"], CLAUSE_REPORT)
        self.assertTrue(is_clause_report(report))

    def test_no_emitted_record_claims_a_jf_name_it_does_not_match(self):
        report = build_report(CLAUSE, {}, ANSWER, "contract/v1", "case-1", "cap-1", "pin-abc", "2026-11-03")
        self.assertNotIn(report["record_type"], JF_NAMES)
        self.assertFalse(JF_REQUIRED <= set(report), "a record with the JF members would need the JF schema")


class LegacyName(unittest.TestCase):
    OLD = {"record_type": LEGACY_CLAUSE_REPORT, "contract": "c", "clause_id": "c.one", "case_id": "k",
           "verdict": "met", "source_capsule_id": "s", "judge_pin_digest": "1" * 64}

    def test_old_records_are_still_read(self):
        self.assertTrue(is_clause_report(self.OLD))
        self.assertTrue(_in_scope(self.OLD, "c", None, None))

    def test_a_jf_record_under_the_old_name_is_not_a_clause_report(self):
        self.assertFalse(is_clause_report(JF_SHAPED))
        self.assertFalse(is_clause_report({**self.OLD, "cases": []}))
        self.assertFalse(_in_scope({**self.OLD, "cases": [{}]}, "c", None, None))
        self.assertEqual(report_determinations([("a", {**JF_SHAPED, "record_type": LEGACY_CLAUSE_REPORT})]), {})

    def test_other_values_are_not_clause_reports(self):
        for body in (None, "x", {}, {"record_type": "something-else/v1"}, {"record_version": LEGACY_CLAUSE_REPORT}):
            self.assertFalse(is_clause_report(body))

    def test_the_weekly_frame_reads_both_names_and_skips_a_jf_record(self):
        bodies = {"new": {"record_type": CLAUSE_REPORT, "period": "day:2026-11-03", "judge_pin_digest": "ab" * 32},
                  "old": {**self.OLD, "period": "day:2026-11-03"},
                  "jf": {**JF_SHAPED, "record_type": LEGACY_CLAUSE_REPORT, "period": "day:2026-11-03",
                         "judge_pin_digest": "cd" * 32}}
        entries = [{"capsule_id": k} for k in bodies]
        reports, unjudged = week_frame(entries, bodies.get, lambda _id: None, {"2026-11-03"})
        self.assertEqual([c for c, _ in reports], ["new", "old"])
        self.assertEqual(unjudged, 0)

    def test_a_rerun_of_a_pre_rename_day_does_not_double_the_weekly_frame(self):
        slot = {"case_id": "k", "clause_id": "c.one", "period": "day:2026-11-03", "verdict": "met",
                "judge_pin_digest": "ab" * 32}
        bodies = {"b-new": {**slot, "record_type": CLAUSE_REPORT},
                  "a-old": {**slot, "record_type": LEGACY_CLAUSE_REPORT},
                  "c-other": {**slot, "record_type": CLAUSE_REPORT, "clause_id": "c.two"},
                  "d-split": {**slot, "record_type": CLAUSE_REPORT, "verdict": "not_met"}}
        checked = []
        reports, _ = week_frame([{"capsule_id": k} for k in bodies], bodies.get, checked.append, {"2026-11-03"})
        self.assertEqual(sorted(c for c, _ in reports), ["a-old", "c-other", "d-split"])
        self.assertEqual(sorted(checked), ["a-old", "c-other", "d-split"])


if __name__ == "__main__":
    unittest.main()
