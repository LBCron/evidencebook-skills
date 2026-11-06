"""`terms studio` (evidencebook-skills#143): the studio-view/v0 input built from workspace files, the
page capsule-viewer draws from it, and `terms verify` on that page (the snapshot only).

The input tests need no viewer. The page tests need a capsule-viewer build with the Studio page
(capsule-viewer PR 304, `npm run build` in ts/) named by $CAPSULE_VIEWER, and skip without one.

    CAPSULE_VIEWER=~/Github/capsule-viewer/ts python3 -m unittest tests.test_terms_studio_page
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import studio_view  # noqa: E402
import terms  # noqa: E402

TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"
VIEWER = os.environ.get("CAPSULE_VIEWER")
HAVE_VIEWER = bool(VIEWER) and (pathlib.Path(VIEWER).expanduser() / "dist" / "index.js").is_file()
GENERATED = "2026-11-05T12:00:00Z"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = pathlib.Path(self.tmp.name).resolve() / "ws"
        self.src = self.pack("stickers")

    def pack(self, pack_id):
        code, res = call("init", "--deals", TRADES, "--workspace", self.ws, "--pack-id", pack_id)
        self.assertEqual(code, 0, res)
        return pathlib.Path(res["pack"])

    def run_pack(self, src, *extra):
        code, res = call("run", src, "--workspace", self.ws, "--generated-at", GENERATED, *extra)
        self.assertEqual(code, 0, res)
        return res


class Input(Base):
    def test_a_pack_with_no_run_has_no_page(self):
        code, res = call("studio", self.src, "--workspace", self.ws, "--viewer", "/nowhere")
        self.assertEqual(code, 1)
        self.assertIn("no run yet", res["error"])

    def test_input_is_built_from_the_files_the_verbs_wrote(self):
        run = self.run_pack(self.src, "--dry-run")
        view = studio_view.build(self.ws, self.src.parent)
        self.assertEqual((view["schema"], view["active"]), ("studio-view/v0", "stickers"))
        (entry,) = view["packs"]
        result = json.loads((pathlib.Path(run["run"]) / "result.json").read_text())
        self.assertEqual(entry["pack_digest"], run["pack_digest"])
        self.assertEqual(entry["page"], "runs/stickers/001/report.html")
        self.assertEqual(entry["shared"], {"dataset_ref": result["dataset_ref"]["digest"], "plan_ref": result["plan_ref"]["digest"]})
        self.assertEqual(entry["bundle_digest"], run["result_sha256"])
        self.assertNotIn("judge", entry)
        self.assertEqual(view["readiness"], json.loads((self.src.parent / "readiness.json").read_text()))
        self.assertEqual(view["history"], [json.loads(l) for l in (self.src.parent / "history.jsonl").read_text().splitlines()])

    def test_the_switch_lists_every_pack_with_a_run_and_only_those(self):
        other, never = self.pack("late"), self.pack("never-run")
        self.run_pack(self.src, "--dry-run")
        self.run_pack(other, "--dry-run")
        view = studio_view.build(self.ws, self.src.parent)
        self.assertEqual([p["pack_id"] for p in view["packs"]], ["late", "stickers"])
        self.assertNotIn("never-run", [p["pack_id"] for p in view["packs"]])
        self.assertEqual(len({json.dumps(p["shared"]) for p in view["packs"]}), 1)  # one dataset and plan, cited by both pages
        self.assertEqual(len({p["bundle_digest"] for p in view["packs"]}), 2)  # two Results, two bundles

    def test_bundle_digest_is_the_digest_the_report_page_prints_for_its_own_record(self):
        run = self.run_pack(self.src, "--dry-run")
        report = (pathlib.Path(run["run"]) / "report.html").read_text()
        (entry,) = studio_view.build(self.ws, self.src.parent)["packs"]
        self.assertIn(f'id="result-digest">{entry["bundle_digest"]}<', report)

    def test_a_deleted_report_is_said_in_words(self):
        run = self.run_pack(self.src)
        (pathlib.Path(run["run"]) / "report.html").unlink()
        with self.assertRaisesRegex(studio_view.StudioError, "report.html is missing"):
            studio_view.build(self.ws, self.src.parent)

    def test_a_pack_edited_since_its_last_run_is_refused(self):
        self.run_pack(self.src, "--dry-run")
        self.src.write_text(self.src.read_text().replace("within 2 days", "within 3 days").replace("delivered_within_days(2)", "delivered_within_days(3)"))
        code, res = call("studio", self.src, "--workspace", self.ws, "--viewer", "/nowhere")
        self.assertEqual(code, 1)
        self.assertIn("changed since its last run", res["error"])

    def test_a_run_linked_from_outside_the_workspace_is_refused(self):
        run = self.run_pack(self.src, "--dry-run")
        outside = pathlib.Path(self.tmp.name) / "elsewhere"
        pathlib.Path(run["run"]).rename(outside)
        pathlib.Path(run["run"]).symlink_to(outside)
        with self.assertRaisesRegex(studio_view.StudioError, "outside the workspace"):
            studio_view.build(self.ws, self.src.parent)

    def test_a_file_linked_from_outside_the_workspace_is_refused(self):
        run = pathlib.Path(self.run_pack(self.src, "--dry-run")["run"])
        outside = pathlib.Path(self.tmp.name) / "outside.json"
        outside.write_bytes((run / "result.json").read_bytes())
        (run / "result.json").unlink()
        (run / "result.json").symlink_to(outside)
        with self.assertRaisesRegex(studio_view.StudioError, "outside the workspace"):
            studio_view.build(self.ws, self.src.parent)

    def test_a_source_linked_from_outside_the_workspace_is_refused(self):
        self.run_pack(self.src, "--dry-run")
        outside = pathlib.Path(self.tmp.name) / "outside.yaml"
        outside.write_bytes(self.src.read_bytes())
        self.src.unlink()
        self.src.symlink_to(outside)
        outside.write_text("title: [unclosed SECRET-MARKER")  # unparsable: a read would put its text in the error
        code, res = call("studio", self.src, "--workspace", self.ws, "--viewer", "/nowhere")
        self.assertEqual(code, 1)
        self.assertIn("outside the workspace", res["error"])
        self.assertNotIn("SECRET-MARKER", res["error"])

    def test_an_unreadable_result_is_a_refusal_not_a_traceback(self):
        run = pathlib.Path(self.run_pack(self.src, "--dry-run")["run"])
        (run / "result.json").chmod(0)
        self.addCleanup((run / "result.json").chmod, 0o644)
        with self.assertRaisesRegex(studio_view.StudioError, "not a terms Result"):
            studio_view.build(self.ws, self.src.parent)

    def test_verify_answers_a_corrupt_snapshot_in_words(self):
        for body in ("[]", "null", "{not json"):
            page = pathlib.Path(self.tmp.name) / "p.html"
            page.write_text('<code data-snapshot-digest>%s</code></p><script type="application/json" data-studio-input>%s</script>'
                            % ("0" * 64, body))
            code, res = call("verify", page)
            self.assertEqual((code, res["verified"], res["scope"]), (1, False, "snapshot"), body)

    def test_one_siblings_bad_state_is_a_refusal_in_words_not_a_traceback(self):
        other = self.pack("late")
        self.run_pack(self.src, "--dry-run")
        self.run_pack(other, "--dry-run")
        (other.parent / "workspace.json").write_text("[]")
        self.assertEqual(studio_view.build(self.ws, self.src.parent)["active"], "stickers")  # an unreadable sibling is skipped, not fatal
        (other.parent / "workspace.json").write_text('{"last_run": {"run": 5}}')
        with self.assertRaisesRegex(studio_view.StudioError, "not a folder"):
            studio_view.build(self.ws, self.src.parent)

    def test_no_viewer_named_is_said_in_words(self):
        self.run_pack(self.src)
        with self.assertRaisesRegex(studio_view.StudioError, "--viewer DIR or \\$CAPSULE_VIEWER"):
            studio_view.render({}, None)
        with self.assertRaisesRegex(studio_view.StudioError, "no dist/index.js"):
            studio_view.render({}, self.tmp.name)


@unittest.skipUnless(HAVE_VIEWER, "needs CAPSULE_VIEWER: a capsule-viewer build with the Studio page")
class Page(Base):
    def studio(self, src=None):
        code, res = call("studio", src or self.src, "--workspace", self.ws, "--viewer", pathlib.Path(VIEWER).expanduser())
        self.assertEqual(code, 0, res)
        return res

    def test_the_page_lists_every_pack_with_a_run_and_hashes_to_its_printed_digest(self):
        other = self.pack("late")
        self.run_pack(self.src, "--dry-run")
        self.run_pack(other, "--dry-run")
        res = self.studio()
        page = pathlib.Path(res["page"])
        self.assertEqual(page, self.ws / "studio.html")
        text = page.read_text()
        for needle in ('data-view="loop"', 'data-view="readiness"', 'data-view="term-map"', 'data-view="switch"',
                       'data-pack="stickers"', 'data-pack="late"', "runs/late/001/report.html"):
            self.assertIn(needle, text)
        self.assertNotIn("never-run", text)
        refs = json.loads((self.ws / "runs/stickers/001/result.json").read_text())
        for digest in (refs["dataset_ref"]["digest"], refs["plan_ref"]["digest"]):
            self.assertIn(digest, text)  # the switch cites the Result's own refs
        declared, actual, view = studio_view.snapshot(text)
        self.assertEqual((declared, actual), (res["snapshot_sha256"], res["snapshot_sha256"]))
        self.assertEqual(view["active"], "stickers")
        code, ver = call("verify", page)
        self.assertEqual((code, ver["verified"], ver["scope"]), (0, True, "snapshot"))
        self.assertIn("checks the snapshot only", ver["note"])

    def test_an_edited_snapshot_fails_verify(self):
        self.run_pack(self.src, "--dry-run")
        page = pathlib.Path(self.studio()["page"])
        page.write_text(page.read_text().replace('"records":10', '"records":11'))
        code, ver = call("verify", page)
        self.assertEqual((code, ver["verified"]), (1, False))
        self.assertIn("does not match the digest", ver["issues"][0])

    def test_the_input_file_is_the_input_the_page_embeds(self):
        self.run_pack(self.src, "--dry-run")
        res = self.studio()
        embedded = studio_view.snapshot(pathlib.Path(res["page"]).read_text())[2]
        written = json.loads(pathlib.Path(res["input"]).read_text())
        for key in ("schema", "active"):
            self.assertEqual(embedded[key], written[key])
        # the renderer normalizes the input (an absent in_force is drawn as null); nothing here ever writes one
        self.assertEqual([{k: v for k, v in e.items() if k != "in_force"} for e in embedded["history"]], written["history"])
        self.assertTrue(all(e.get("in_force") is None for e in embedded["history"]))
        self.assertEqual([p["pack_id"] for p in embedded["packs"]], ["stickers"])
        # the renderer normalizes the input: filled_rate is accepted and dropped, the terms stay
        self.assertEqual([t["term"] for t in embedded["readiness"]["terms"]], [t["term"] for t in written["readiness"]["terms"]])

    def test_an_edit_makes_a_new_digest_and_the_loop_says_so_not_yet(self):
        self.run_pack(self.src, "--dry-run")
        code, res = call("publish", self.src, "--workspace", self.ws)
        self.assertEqual(code, 0, res)  # the first digest is published; the edited one is not
        text = pathlib.Path(self.studio()["page"]).read_text()
        self.assertIn('data-stage="published" data-state="done"', text)
        self.assertIn('data-stage="switched_on" data-state="not-recorded"', text)  # a publish is not an install; we write no in_force
        text = self.src.read_text()
        self.src.write_text(text.replace("pack_version: 0.1.0", "pack_version: 0.1.1").replace("within 2 days", "within 3 days").replace("delivered_within_days(2)", "delivered_within_days(3)"))
        self.run_pack(self.src)  # a real run under the new digest
        text = pathlib.Path(self.studio()["page"]).read_text()
        self.assertIn('data-stage="tried" data-state="done"', text)
        self.assertIn('data-stage="published" data-state="not-yet"', text)


if __name__ == "__main__":
    unittest.main()
