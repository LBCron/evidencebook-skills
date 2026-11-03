"""The record name daily-judge-and-close seals for one clause of one case.

It was sealed as `evaluation-report/v1` until 2026-11-03, a name the AAC Judge
Record Family owns for a different shape (`cases[]` of cited acts and a cited
method, `additionalProperties: false`). This record carries `clause_id`,
`rationale`, `source_capsule_id` and recomputed determinations, which that
schema cannot hold, so it has its own name (evidencebook-skills#113).

Records sealed before the rename keep the old name forever. A reader accepts
one by shape, not by name alone: the old name counts as ours only with a
`record_type` and no `cases[]`, so a real JF evaluation-report sealed later is
never misread as a clause report.
"""

CLAUSE_REPORT = "clause-report/v1"
LEGACY_CLAUSE_REPORT = "evaluation-report/v1"


def is_clause_report(body):
    """Whether `body` (a sealed payload) is one of this contract's clause reports."""
    if not isinstance(body, dict):
        return False
    record_type = body.get("record_type")
    if record_type == CLAUSE_REPORT:
        return True
    return record_type == LEGACY_CLAUSE_REPORT and "cases" not in body
