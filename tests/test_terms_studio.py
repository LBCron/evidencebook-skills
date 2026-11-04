"""The Terms Pack Studio verbs (scripts/studio/terms) and the sticker_deal evaluator
(evidencebook-skills#117), end to end on tests/fixtures/sticker-sale/trades.json:
the ten-sale rehearsal reads 9 of 10 with the price miss, the page verifies
offline and carries result.json's bytes, `compare` of a 1-day and a 2-day pack
shows ten ties on that row and both digests, and `run` writes only into the
workspace it is given.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import jsonschema  # noqa: E402

import sticker_deal  # noqa: E402
import terms  # noqa: E402

SOURCE = ROOT / "packs" / "sticker-sale" / "pack-source.yaml"
TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"
GENERATED = "2026-11-04T12:00:00Z"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


def listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class StickerDeal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = pathlib.Path(self.tmp.name)
        self.ws = self.tmp_path / "ws"

    def two_day_source(self):
        text = SOURCE.read_text().replace("within 1 day", "within 2 days").replace(
            "delivered_within_days(1)", "delivered_within_days(2)")
        path = self.tmp_path / "two.yaml"
        path.write_text(text)
        return path

    def rehearse(self, src):
        code, res = call("run", src, "--deals", TRADES, "--dry-run", "--workspace", self.ws, "--generated-at", GENERATED)
        self.assertEqual(code, 0, res)
        return res

    def test_lint_and_test_pass_on_the_shipped_pack(self):
        self.assertEqual(call("lint", SOURCE)[0], 0)
        code, res = call("test", SOURCE)
        self.assertEqual(code, 0, res)
        self.assertEqual([r["passed"] for r in res["rows"]], [True, True, True])

    def test_lint_refuses_a_row_without_a_check_or_with_a_bad_one(self):
        text = SOURCE.read_text()
        for name, bad in (("nocheck", text.replace("    check: price_as_offered\n", "")),
                          ("badcheck", text.replace("price_as_offered\n    proves", "free_stickers\n    proves")),
                          ("noarg", text.replace("delivered_within_days(1)", "delivered_within_days")),
                          ("model", text.replace("tier: recomputed", "tier: judged", 1))):
            path = self.tmp_path / f"{name}.yaml"
            path.write_text(bad)
            code, res = call("lint", path)
            self.assertEqual(code, 1, name)
            self.assertFalse(res["valid"], name)

    def test_the_ten_trade_rehearsal_reads_nine_of_ten_with_the_price_miss(self):
        res = self.rehearse(SOURCE)
        self.assertEqual((res["came_through"], res["sales"], res["rehearsal"]), (9, 10, True))
        result = json.loads(pathlib.Path(res["result"]).read_bytes())
        misses = {c["id"] for c in result["claims"] if c["verdict"] == "not_met"}
        self.assertEqual(misses, {"sticker-07::price_as_offered"})
        self.assertTrue(result["x-rehearsal"])

    def test_the_result_validates_against_the_evidence_result_schema(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_result_v0_schema as t  # noqa: E402
        validator = jsonschema.Draft202012Validator(json.loads(t.SCHEMA_PATH.read_bytes()))
        result = json.loads(pathlib.Path(self.rehearse(SOURCE)["result"]).read_bytes())
        self.assertEqual([e.message for e in validator.iter_errors(result)], [])

    def test_the_page_verifies_offline_and_embeds_the_result_bytes(self):
        res = self.rehearse(SOURCE)
        page = pathlib.Path(res["page"])
        raw = pathlib.Path(res["result"]).read_bytes()
        self.assertIn(raw.decode(), page.read_text())
        self.assertIn("REHEARSAL", page.read_text())
        code, ver = call("verify", page)
        self.assertEqual((code, ver["verified"]), (0, True), ver)
        # a page edited after the run no longer verifies
        page.write_text(page.read_text().replace("9 of 10", "10 of 10"))
        self.assertEqual(call("verify", page)[0], 1)
        page.write_text(page.read_text().replace('"claims"', '"claimz"', 1))
        self.assertEqual(call("verify", page)[0], 1)

    def test_a_run_without_dry_run_is_not_stamped(self):
        code, res = call("run", SOURCE, "--deals", TRADES, "--workspace", self.ws, "--generated-at", GENERATED)
        self.assertEqual(code, 0)
        self.assertFalse(res["rehearsal"])
        self.assertNotIn("REHEARSAL", pathlib.Path(res["page"]).read_text())
        self.assertEqual(call("verify", res["page"])[0], 0)

    def test_compare_one_day_to_two_days_shows_ten_ties_and_both_digests(self):
        first, second = self.rehearse(SOURCE), self.rehearse(self.two_day_source())
        code, cmp = call("compare", first["run"], second["run"])
        self.assertEqual(code, 0, cmp)
        self.assertTrue(cmp["same_rows"])
        by_row = {r["row"]: r for r in cmp["rows"]}
        within = by_row["delivered_within_days"]
        self.assertEqual((within["result"], within["improved"], within["regressed"], within["tied"]),
                         ("Tie", 0, 0, 10))
        self.assertTrue(within["row_changed"])
        self.assertFalse(by_row["price_as_offered"]["row_changed"])
        self.assertEqual(cmp["before"]["pack_digest"], first["pack_digest"])
        self.assertEqual(cmp["after"]["pack_digest"], second["pack_digest"])
        self.assertNotEqual(first["pack_digest"], second["pack_digest"])

    def test_compare_reports_improvement_regression_and_tradeoff(self):
        base = json.loads(pathlib.Path(self.rehearse(SOURCE)["result"]).read_bytes())
        def variant(flips):
            doc = json.loads(json.dumps(base))
            for claim in doc["claims"]:
                if claim["id"] in flips:
                    claim["verdict"] = flips[claim["id"]]
            path = self.tmp_path / f"v{len(flips)}-{abs(hash(tuple(flips.items())))}.json"
            path.write_text(json.dumps(doc))
            return path
        better = variant({"sticker-07::price_as_offered": "met"})
        worse = variant({"sticker-01::price_as_offered": "not_met"})
        both = variant({"sticker-07::price_as_offered": "met", "sticker-01::price_as_offered": "not_met"})
        base_path = pathlib.Path(self.rehearse(SOURCE)["result"])
        got = {name: {r["row"]: r["result"] for r in call("compare", base_path, p)[1]["rows"]}["price_as_offered"]
               for name, p in (("better", better), ("worse", worse), ("both", both))}
        self.assertEqual(got, {"better": "Improvement", "worse": "Regression", "both": "Tradeoff"})

    def test_compare_flags_rows_added_or_removed_and_refuses_different_sales(self):
        first = self.rehearse(SOURCE)
        short = self.tmp_path / "short.yaml"
        short.write_text(SOURCE.read_text().split("  - id: price_as_offered")[0])
        second = self.rehearse(short)
        code, cmp = call("compare", first["run"], second["run"])
        self.assertEqual(code, 0)
        self.assertFalse(cmp["same_rows"])
        self.assertEqual(cmp["rows_removed"], ["price_as_offered"])
        fewer = self.tmp_path / "fewer.json"
        fewer.write_text(json.dumps(json.loads(TRADES.read_text())["trades"][:5]))
        code, third = call("run", SOURCE, "--deals", fewer, "--dry-run", "--workspace", self.ws)
        self.assertEqual(call("compare", first["run"], third["run"])[0], 1)

    def test_run_and_publish_write_only_into_the_workspace(self):
        src = self.tmp_path / "src"
        src.mkdir()
        pack = src / "pack-source.yaml"
        pack.write_text(SOURCE.read_text())
        before = listing(src)
        self.rehearse(pack)
        code, pub = call("publish", pack, "--workspace", self.ws)
        self.assertEqual(code, 0, pub)
        self.assertEqual(listing(src), before)
        files = listing(self.ws)
        self.assertTrue(files and all(f.startswith(("runs", "published")) for f in files), files)
        self.assertIn(pub["definition_digest"][:12], pub["published"])
        compiled = json.loads(pathlib.Path(pub["compiled"]).read_text())
        self.assertEqual(compiled["definition_digest"], pub["definition_digest"])

    def test_a_workspace_link_pointing_out_is_refused(self):
        outside = self.tmp_path / "outside"
        outside.mkdir()
        self.ws.mkdir()
        (self.ws / "runs").symlink_to(outside)
        code, res = call("run", SOURCE, "--deals", TRADES, "--dry-run", "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertEqual(listing(outside), [])

    def test_the_shipped_compiled_pack_is_current(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_compile.py"), "compile", str(SOURCE),
                              "--out", "packs/sticker-sale/compiled"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        committed = json.loads((ROOT / "packs" / "sticker-sale" / "compiled" / "compiled.json").read_text())
        self.assertEqual(committed["definition_digest"], json.loads(out.stdout)["definition_digest"])


class Folds(unittest.TestCase):
    def test_a_missing_field_is_not_evaluable_never_not_met(self):
        for name, arg in (("paid_before_delivered", None), ("delivered_within_days", 1), ("price_as_offered", None)):
            fold, _ = sticker_deal.CHECKS[name]
            self.assertEqual(fold({}, arg), "not_evaluable", name)
        fold, _ = sticker_deal.CHECKS["delivered_within_days"]
        self.assertEqual(fold({"paid_at": "2026-11-01T10:00:00Z"}, 1), "not_evaluable")

    def test_delivered_within_days_is_inclusive_and_reads_whole_days(self):
        fold, _ = sticker_deal.CHECKS["delivered_within_days"]
        sale = lambda d: {"paid_at": "2026-11-01T10:00:00Z", "delivered_at": d}  # noqa: E731
        self.assertEqual(fold(sale("2026-11-02T10:00:00Z"), 1), "met")
        self.assertEqual(fold(sale("2026-11-02T10:00:01Z"), 1), "not_met")
        self.assertEqual(fold(sale("2026-11-02T10:00:01Z"), 2), "met")

    def test_paid_before_delivered_fails_when_delivery_comes_first(self):
        fold, _ = sticker_deal.CHECKS["paid_before_delivered"]
        self.assertEqual(fold({"paid_at": "2026-11-01T10:00:00Z", "delivered_at": "2026-11-01T09:00:00Z"}, None), "not_met")


if __name__ == "__main__":
    unittest.main()
