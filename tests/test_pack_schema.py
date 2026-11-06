"""The pack JSON Schema (schemas/pack-source.schema.json) and `terms lint` on every
kind of pack (evidencebook-skills#126; Terms Pack Studio PRD v5 section 15 item 1):
the existing admission, live, report (after-the-fact), deal and conduct packs all
pass, and a pack that breaks the schema is refused by the field.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import copy
import glob
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("scripts", "scripts/evaluators", "scripts/studio"):
    sys.path.insert(0, str(ROOT / sub))

import yaml  # noqa: E402

import admission_pack  # noqa: E402
import deal_pack  # noqa: E402
import live_pack  # noqa: E402
import pack_compile  # noqa: E402
import pack_schema  # noqa: E402
import terms  # noqa: E402

SAMPLES = {
    "admission": ROOT / "packs/admission-baseline/pack-source.yaml",
    "deal": ROOT / "packs/sticker-sale/pack-source.yaml",
    "conduct": ROOT / "tests/fixtures/terms-samples/conduct/pack-source.yaml",
    "live": ROOT / "tests/fixtures/live-pack/airline-engagement-1.0.1/pack-source.yaml",
    "after_the_fact": ROOT / "packs/airline-support-outcomes/pack-source.yaml",
}
EVERY_PACK = sorted(glob.glob(str(ROOT / "packs/*/pack-source.yaml"))
                    + glob.glob(str(ROOT / "tests/fixtures/**/pack-source.yaml"), recursive=True))


def load(path):
    return pack_compile.load_source(pathlib.Path(path).read_text())


def lint(path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main(["lint", str(path)])
    return code, json.loads(buf.getvalue())


class EveryExistingPackPasses(unittest.TestCase):
    def test_each_kind_has_a_sample(self):
        for kind, path in SAMPLES.items():
            self.assertEqual(pack_schema.kind_of(load(path)), kind, path)

    def test_every_pack_in_the_repo_passes_the_schema_and_lint(self):
        self.assertGreaterEqual(len(EVERY_PACK), 16)
        for path in EVERY_PACK:
            with self.subTest(path=path):
                self.assertEqual(pack_schema.schema_issues(load(path)), [])
                code, res = lint(path)
                self.assertEqual((code, res["issues"]), (0, []))
                self.assertTrue(res["valid"])

    def test_lint_names_the_kind(self):
        for kind, path in SAMPLES.items():
            self.assertEqual(lint(path)[1]["kind"], kind)


class SchemaIsTheStructure(unittest.TestCase):
    """The schema's closed sets are the ones the validators hold; a change to
    one must be made to both."""

    def setUp(self):
        self.defs = pack_schema.schema()["$defs"]

    def test_scope_kinds(self):
        self.assertEqual(set(pack_schema.schema()["properties"]["scope"]["properties"]["kind"]["enum"]),
                         set(live_pack.SCOPE_KINDS))
        self.assertEqual(set(pack_schema.KINDS), set(live_pack.SCOPE_KINDS))

    def test_closed_member_sets(self):
        self.assertEqual(set(self.defs["deal"]["properties"]), deal_pack.TOP_KEYS)
        self.assertEqual(set(self.defs["deal"]["properties"]["rows"]["items"]["properties"]), deal_pack.ROW_KEYS)
        self.assertEqual(set(self.defs["admission"]["properties"]), admission_pack.ADMISSION_KEYS)
        self.assertEqual(set(self.defs["admission"]["properties"]["rows"]["items"]["properties"]), admission_pack.ROW_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]), live_pack.LIVE_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]["obligations"]["items"]["properties"]), live_pack.OBLIGATION_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]["outcomes"]["items"]["properties"]), live_pack.OUTCOME_KEYS)
        self.assertEqual(set(self.defs["after_the_fact"]["properties"]["report"]["properties"]),
                         set(pack_compile.REPORT_KEYS) | {"card"})
        self.assertEqual(set(self.defs["live"]["properties"]["outcomes"]["items"]["properties"]["clause"]["properties"]),
                         live_pack.CLAUSE_KEYS)

    def test_closed_value_sets(self):
        live = self.defs["live"]["properties"]
        self.assertEqual(live["obligations"]["items"]["properties"]["mode"]["enum"], list(live_pack.MODES))
        self.assertEqual(live["outcomes"]["items"]["properties"]["forward_verdict"]["enum"], list(live_pack.FORWARD_VERDICTS))
        adm = self.defs["admission"]["properties"]["rows"]["items"]["properties"]
        self.assertEqual(adm["source"]["enum"], list(admission_pack.SOURCES))
        self.assertEqual(adm["check"]["enum"], list(admission_pack.PREDICATES))
        crit = self.defs["after_the_fact"]["properties"]["checks"]["items"]["properties"]["criteria"]["items"]["properties"]
        self.assertEqual(set(crit["tier"]["enum"]), pack_compile.TIERS)


class BreakingTheSchema(unittest.TestCase):
    """Each edit of a sample pack is refused, naming the field."""

    def refused(self, kind, edit, *want):
        source = copy.deepcopy(load(SAMPLES[kind]))
        edit(source)
        issues = pack_schema.schema_issues(source)
        self.assertTrue(issues, "the edited pack was accepted")
        for w in want:
            self.assertTrue(any(w in i for i in issues), f"{w!r} not named in {issues}")
        return issues

    def test_deal(self):
        self.refused("deal", lambda s: s["rows"][0].update(tier="judged"), "rows[0].tier")
        self.refused("deal", lambda s: s["rows"][0].update(colour="red"), "rows[0].colour")
        self.refused("deal", lambda s: s.pop("title"), "title is required")
        self.refused("deal", lambda s: s["rows"][0].update(proves=["nonsense"]), "rows[0].proves[0]")

    def test_admission(self):
        self.refused("admission", lambda s: s["budget"].update(max_asks=-1), "budget.max_asks")
        self.refused("admission", lambda s: s["rows"][0].update(check="card.nope"), "rows[0].check")
        self.refused("admission", lambda s: s.update(missing="GO"), "missing")
        self.refused("admission", lambda s: s.update(extra=1), "extra")

    def test_live(self):
        self.refused("live", lambda s: s["obligations"][0].update(mode="guess"), "obligations[0].mode")
        self.refused("live", lambda s: s.update(holds_integration="bogus"), "holds_integration")
        self.refused("live", lambda s: s["outcomes"][0].update(forward_verdict="MAYBE"), "outcomes[0].forward_verdict")
        self.refused("live", lambda s: s.update(colour="red"), "colour")

    def test_the_judge_member_is_checked_by_the_schema(self):
        self.refused("after_the_fact", lambda s: s["judge"].update(model_id=[]), "judge.model_id")
        self.refused("after_the_fact", lambda s: s["judge"].update(min_confidence=2), "judge.min_confidence")
        self.refused("after_the_fact", lambda s: s["report"].update(template=[]), "report.template")
        self.refused("live", lambda s: s["profiles"].append({"profile_id": [], "counterparty_binding": {"direct": "x"}})
                     if "profiles" in s else s.update(profiles=[{"profile_id": [], "counterparty_binding": {"direct": "x"}}]),
                     "profiles[")

    def test_a_nested_choice_names_the_member_that_is_wrong(self):
        """A constraint, fold, instrument or on_fail is one of two forms; the error
        names the field of the form the member chose, never the other form's."""
        payments = ROOT / "tests/fixtures/live-pack/payments-safety-1.0.0/pack-source.yaml"
        SAMPLES["payments"] = payments
        self.addCleanup(SAMPLES.pop, "payments")
        want = (
            (lambda s: s["constraints"][0].pop("check"), ["constraints[0].check is required"]),
            (lambda s: s["constraints"][0].update(wicket_id=[]), ["constraints[0].wicket_id"]),
            (lambda s: s["constraints"][0].update(config="x"), ["constraints[0].config"]),
            (lambda s: s["folds"][0].update(file=[]), ["folds[0].file"]),
        )
        for edit, names in want:
            issues = self.refused("payments", edit, *names)
            self.assertFalse(any("is not a field" in i for i in issues), issues)
        issues = self.refused("admission", lambda s: s["rows"][0].update(on_fail={"cap": []}), "rows[0].on_fail.cap")
        self.assertEqual(len(issues), 1, issues)
        self.refused("admission", lambda s: s["rows"][0].update(on_fail="MAYBE"), "rows[0].on_fail 'MAYBE'")

    def test_report(self):
        self.refused("after_the_fact", lambda s: s["checks"][0]["criteria"][0].update(tier="guessed"),
                     "checks[0].criteria[0].tier")
        self.refused("after_the_fact", lambda s: s.pop("checks"), "checks is required")
        self.refused("after_the_fact", lambda s: s["checks"][0]["criteria"][0].update(recompute_eligible="no"),
                     "checks[0].criteria[0].recompute_eligible")

    def test_conduct(self):
        self.refused("conduct", lambda s: s["checks"][0]["criteria"][0].update(tier="guessed"),
                     "checks[0].criteria[0].tier")
        self.refused("conduct", lambda s: s["scope"].update(kind="conducts"), "scope.kind")
        self.refused("conduct", lambda s: s["scope"].update(audience="counterparty"), "scope.audience")

    def test_an_unknown_kind_names_the_kinds_once(self):
        source = load(SAMPLES["deal"])
        source["scope"]["kind"] = "receipt"
        self.assertEqual(pack_schema.schema_issues(source),
                         ["scope.kind 'receipt' must be one of ['live', 'after_the_fact', 'admission', 'deal', 'conduct']"])

    def test_not_a_mapping(self):
        self.assertEqual(pack_schema.schema_issues(["a"]), ["pack source must be a mapping"])
        self.assertIsNone(pack_schema.kind_of(["a"]))

    def test_a_scope_that_is_not_a_mapping_is_one_issue(self):
        for scope in ("x", [], None):
            source = load(SAMPLES["deal"])
            source["scope"] = scope
            self.assertEqual(pack_schema.schema_issues(source), ["scope must be a mapping with a kind"], scope)

    def test_an_unquoted_date_as_the_kind_is_refused_and_lint_prints_it(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = pathlib.Path(d.name) / "pack-source.yaml"
        p.write_text("scope:\n  kind: 2026-01-01\npack_id: x\n")
        code, res = lint(p)
        self.assertEqual((code, res["valid"], res["kind"]), (1, False, None))
        self.assertIn("scope.kind", res["issues"][0])


class LintCli(unittest.TestCase):
    def write(self, text):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = pathlib.Path(d.name) / "pack-source.yaml"
        p.write_text(text)
        return p

    def test_lint_refuses_a_schema_break_on_a_non_deal_pack_and_names_the_field(self):
        source = load(SAMPLES["conduct"])
        source["checks"][0]["criteria"][0]["tier"] = "guessed"
        code, res = lint(self.write(yaml.safe_dump(source)))
        self.assertEqual(code, 1)
        self.assertFalse(res["valid"])
        self.assertEqual(res["kind"], "conduct")
        self.assertTrue(any("checks[0].criteria[0].tier" in i for i in res["issues"]), res)

    def test_lint_runs_the_cross_field_rules_after_the_schema(self):
        source = load(SAMPLES["deal"])
        source["rows"][1]["statement"] = "Delivered promptly."
        code, res = lint(self.write(yaml.safe_dump(source)))
        self.assertEqual(code, 1)
        self.assertTrue(any("statement must say" in i for i in res["issues"]), res)

    def test_lint_reads_an_unreadable_file(self):
        code, res = lint(self.write("a: [unclosed"))
        self.assertEqual((code, res["valid"]), (1, False))
        self.assertIn("cannot read", res["issues"][0])

    def test_a_missing_file(self):
        code, res = lint("/nonexistent/pack-source.yaml")
        self.assertEqual((code, res["valid"]), (1, False))


def run_test(path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main(["test", str(path)])
    return code, json.loads(buf.getvalue())


FUZZED = [str(p) for p in SAMPLES.values()] + sorted(glob.glob(str(ROOT / "tests/fixtures/terms-samples/*/pack-source.yaml")))


def _leaves(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _leaves(v, path + (i,))
    yield path


class LintNeverCrashes(unittest.TestCase):
    """The class of defect behind a lint that dies on a malformed member instead of
    naming it: every member of every pack in the repo, replaced by a value of the
    wrong type, must come back as issues (or as a valid pack), never as an exception."""

    BAD = ([], {}, 7, None, "x")

    def test_a_wrong_typed_member_is_reported_not_raised(self):
        for path in FUZZED:
            base = load(path)
            for where in _leaves(base):
                if not where:
                    continue
                for bad in self.BAD:
                    source = copy.deepcopy(base)
                    node = source
                    for p in where[:-1]:
                        node = node[p]
                    node[where[-1]] = bad
                    try:
                        if not pack_schema.schema_issues(source):
                            pack_compile.validate_source(source, pathlib.Path(path).parent)
                    except Exception as e:  # noqa: BLE001
                        self.fail(f"{path}: {'.'.join(map(str, where))} = {bad!r} raised {type(e).__name__}: {e}")


class TestOnEveryKind(unittest.TestCase):
    """`terms test` takes a pack of any kind and its met / not_met cases for every row.
    Only a deal pack has an evaluator `terms test` can run; the other kinds are decided by
    capsule-engine or a pinned judge, so their cases are checked against the pack
    and reported not evaluated, never passed."""

    SAMPLES = {k: ROOT / f"tests/fixtures/terms-samples/{k}/pack-source.yaml"
               for k in ("admission", "live", "report", "conduct")}

    def test_deal_runs_both_cases_of_every_row(self):
        code, res = run_test(SAMPLES["deal"])
        self.assertEqual((code, res["passed"], res["kind"]), (0, True, "deal"))
        self.assertTrue(all(r["evaluated"] and (r["met_case"], r["miss_case"]) == ("met", "not_met") for r in res["rows"]))

    def test_each_other_kind_checks_its_fixtures_and_says_nothing_was_run(self):
        for name, path in self.SAMPLES.items():
            with self.subTest(kind=name):
                code, res = run_test(path)
                self.assertEqual(code, 0, res)
                self.assertIsNone(res["passed"])
                self.assertTrue(res["fixtures_valid"])
                self.assertEqual((res["evaluated"], res["not_evaluated"]), (0, res["cases"]))
                self.assertTrue(all(not r["evaluated"] and r["reason"] for r in res["rows"]))

    def copy_sample(self, name):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        import shutil
        dst = pathlib.Path(d.name) / "pack"
        shutil.copytree(self.SAMPLES[name].parent, dst)
        return dst

    def test_a_row_without_a_not_met_case_is_refused(self):
        dst = self.copy_sample("conduct")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"] = [c for c in doc["cases"] if c["case"] == "met"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertTrue(any("has no not_met case" in i for i in res["issues"]), res)

    def test_a_case_for_a_row_the_pack_lacks_is_refused(self):
        dst = self.copy_sample("admission")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"].append({"row": "ghost", "case": "met", "input": {"a": 1}})
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("'ghost'" in i for i in res["issues"]), res)

    def test_a_missing_fixture_file_is_refused(self):
        dst = self.copy_sample("report")
        (dst / "fixtures/two-case.json").unlink()
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("is missing" in i for i in res["issues"]), res)

    def test_a_pack_that_breaks_the_schema_is_not_tested(self):
        dst = self.copy_sample("live")
        p = dst / "pack-source.yaml"
        p.write_text(p.read_text().replace("holds_integration: stubbed", "holds_integration: bogus"))
        code, res = run_test(p)
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertTrue(any("holds_integration" in i for i in res["issues"]), res)

    def test_the_same_input_in_both_cases_is_refused(self):
        dst = self.copy_sample("report")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        for c in doc["cases"]:
            c["input"] = doc["cases"][0]["input"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("same input" in i for i in res["issues"]), res)

    def test_an_evaluator_pack_is_not_said_to_be_judged(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        dst = pathlib.Path(d.name) / "pack"
        (dst / "fixtures").mkdir(parents=True)
        src = ROOT / "packs/inference-deals/pack-source.yaml"
        (dst / "pack-source.yaml").write_text(src.read_text())
        rows = terms.two_case.row_ids(load(src))
        cases = [{"row": r, "case": c, "input": {"case": c, "row": r}} for r in rows for c in ("met", "not_met")]
        (dst / "fixtures/two-case.json").write_text(json.dumps({"pack": load(src)["pack_id"], "cases": cases}))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 0, res)
        reasons = {r["reason"] for r in res["rows"]}
        self.assertEqual(len(reasons), 1)
        self.assertIn("inference_deals evaluator", reasons.pop())

    def test_sample_fixtures_name_their_own_pack(self):
        for name, path in self.SAMPLES.items():
            doc = json.loads((path.parent / "fixtures/two-case.json").read_text())
            self.assertEqual(doc["pack"], load(path)["pack_id"], name)


class ConductIsAScopeKind(unittest.TestCase):
    def test_a_conduct_pack_validates_and_compiles_like_a_report_pack(self):
        source = load(SAMPLES["conduct"])
        self.assertEqual(live_pack.scope_kind(source), "conduct")
        self.assertEqual(pack_compile.validate_source(source), [])
        self.assertEqual(pack_compile.compile_pack(source, "x/y")[0]["contract_ref"], "asg/conduct-sample@0.1.0")

    def test_the_source_digest_names_the_kind(self):
        a = load(SAMPLES["conduct"])
        b = copy.deepcopy(a)
        b["scope"]["kind"] = "after_the_fact"
        self.assertNotEqual(pack_compile.source_digest(a), pack_compile.source_digest(b))


if __name__ == "__main__":
    unittest.main()
