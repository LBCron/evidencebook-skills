"""`terms init`, the field census and the readiness table (evidencebook-skills#127):
a dataset with no terms yields a pack whose every term has one of the five statuses,
"needs a field" names the field the census lacks, and readiness follows each edit,
label and run with no other step.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import readiness  # noqa: E402
import terms  # noqa: E402

TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


class Census(unittest.TestCase):
    def test_counts_filled_fields_and_ignores_empty_ones(self):
        c = readiness.census([{"a": 1, "b": {"c": "x"}, "e": ""}, {"a": 2, "b": {"c": None}, "e": [], "l": [{"k": 1}, {"k": 2}]}])
        got = {f["field"]: (f["filled"], f["rate"]) for f in c["fields"]}
        self.assertEqual(got, {"a": (2, 1.0), "b.c": (1, 0.5), "l[].k": (1, 0.5)})
        self.assertEqual(c["records"], 2)

    def test_empty_dataset(self):
        self.assertEqual(readiness.census([]), {"records": 0, "fields": []})


class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = pathlib.Path(self.tmp.name) / "ws"
        self.deals = pathlib.Path(self.tmp.name) / "sales.json"

    def init(self, sales, *extra):
        self.deals.write_text(json.dumps(sales))
        return call("init", "--deals", self.deals, "--workspace", self.ws, *extra)

    def sale(self, **kw):
        base = {"deal_id": "d1", "offered_price": 500, "accepted_price": 500,
                "paid_at": "2026-10-11T10:00:00Z", "delivered_at": "2026-10-11T15:30:00Z"}
        base.update(kw)
        return base

    def test_every_term_has_one_of_the_five_statuses(self):
        code, res = call("init", "--deals", TRADES, "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        self.assertTrue(res["terms"])
        self.assertEqual({t["status"] for t in res["terms"]} - set(readiness.STATUSES), set())
        self.assertEqual(set(res["counts"]), set(readiness.STATUSES))
        self.assertEqual(sum(res["counts"].values()), len(res["terms"]))
        # a full dataset has every field the rows read, so only "needs a field" is absent
        self.assertEqual([s for s in readiness.STATUSES if not res["counts"][s]], ["needs a field"])
        self.assertEqual(res["records"], 10)

    def test_the_proposed_pack_lints_and_tests(self):
        _, res = self.init([self.sale()])
        self.assertEqual(call("lint", res["pack"])[0], 0)
        self.assertEqual(call("test", res["pack"])[0], 0)

    def test_needs_a_field_names_the_missing_field(self):
        sale = self.sale()
        del sale["delivered_at"]
        _, res = self.init([sale])
        by = {t["term"]: t for t in res["terms"]}
        self.assertEqual(by["paid_before_delivered"]["status"], "needs a field")
        self.assertEqual(by["paid_before_delivered"]["missing_fields"], ["delivered_at"])
        self.assertIn("delivered_at", by["paid_before_delivered"]["detail"])
        self.assertEqual(by["price_as_offered"]["status"], "checkable now")

    def test_init_never_overwrites_a_pack(self):
        self.init([self.sale()])
        code, res = self.init([self.sale()])
        self.assertEqual(code, 1)
        self.assertIn("exists", res["error"])

    def test_rejects_a_bad_pack_id_and_an_escaping_one(self):
        self.assertEqual(self.init([self.sale()], "--pack-id", "../x")[0], 1)

    def test_readiness_follows_an_edit_a_label_and_a_run_with_no_other_step(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        table = lambda: json.loads((folder / "readiness.json").read_text())  # noqa: E731
        status = lambda t, term: {x["term"]: x["status"] for x in t["terms"]}.get(term)  # noqa: E731
        self.assertEqual(status(table(), "matched_description"), "needs examples")

        # an edit: drop a row, then lint
        src = pathlib.Path(res["pack"])
        src.write_text(src.read_text().replace("- id: price_as_offered", "- id: price_as_quoted"))
        self.assertEqual(call("lint", src)[0], 0)
        self.assertIsNone(status(table(), "price_as_offered"))
        self.assertEqual(status(table(), "price_as_quoted"), "checkable now")

        # a label: four sales labelled, then test
        (folder / "labels.json").write_text(json.dumps({"matched_description": [{"deal_id": f"d{i}", "met": True} for i in range(4)]}))
        call("test", src)
        row = {x["term"]: x for x in table()["terms"]}["matched_description"]
        self.assertIn("4 labelled", row["detail"])

        # a run over sales that now carry a buyer confirmation: the census, and so the table, moves
        sales = [self.sale(buyer_confirmed_at="2026-10-12T10:00:00Z")]
        self.deals.write_text(json.dumps(sales))
        self.assertEqual(call("run", src, "--deals", self.deals, "--dry-run", "--workspace", self.ws)[0], 0)
        self.assertEqual({f["field"] for f in json.loads((folder / "census.json").read_text())["fields"]} >= {"buyer_confirmed_at"}, True)
        # the term still needs the other side: a buyer's confirmation field is not the buyer's own record
        self.assertEqual(status(table(), "buyer_confirmed_receipt"), "needs the other side")

    def test_readiness_verb_prints_the_same_table(self):
        _, res = self.init([self.sale()])
        code, again = call("readiness", res["pack"])
        self.assertEqual(code, 0)
        self.assertEqual(again["terms"], res["terms"])

    def test_readiness_refuses_a_pack_with_no_census(self):
        code, res = call("readiness", ROOT / "packs" / "sticker-sale" / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertIn("terms init", res["error"])

    def test_verbs_leave_a_pack_without_a_census_alone(self):
        folder = pathlib.Path(self.tmp.name) / "plain"
        folder.mkdir()
        src = folder / "pack-source.yaml"
        src.write_text((ROOT / "packs" / "sticker-sale" / "pack-source.yaml").read_text())
        call("lint", src)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["pack-source.yaml"])


if __name__ == "__main__":
    unittest.main()
