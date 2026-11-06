"""The Studio page of a Terms Pack workspace (evidencebook-skills#143, capsule-viewer#291).

`build(ws, folder)` makes the `studio-view/v0` input (capsule-viewer docs/design/studio-page.md
section 2) from files `terms` verbs already wrote, and from nothing else:

    packs/<id>/workspace.json   the dataset digest, the latest run (`last_run`)
    runs/<id>/<n>/result.json   `x-pack.definition_digest`, the pack digest of that run
    runs/<id>/<n>/report.html   the pack's report page, linked from the switch
    packs/<id>/readiness.json   the active pack's readiness table
    packs/<id>/history.jsonl    the active pack's lines, one per pack digest

One Result per bundle (Steven's ruling): each pack's page cites the digest of the sales it was
run over, `shared = {kind: dataset_ref, digest: workspace.json dataset.sales_digest}`. A deal
Result names no judge, so `judge` is left out. `render` hands the input to capsule-viewer's
`studioViewDocument` through studio_page.mjs; the renderer is not reimplemented here.

`snapshot` is what `terms verify` checks on the page: the SHA-256 of the embedded input against
the digest the page prints. That is the snapshot only; the workspace files are not sealed evidence.
"""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess

import yaml

import workspace as wsm

SCHEMA = "studio-view/v0"
BRIDGE = pathlib.Path(__file__).with_name("studio_page.mjs")
SHARED_KIND = "dataset_ref"


class StudioError(ValueError):
    """A refusal, said in words (terms.main prints it like a TermsError)."""


def _title(folder):
    try:
        title = yaml.safe_load((folder / "pack-source.yaml").read_text(encoding="utf-8")).get("title")
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    return title if isinstance(title, str) and title else None


def _entry(ws, folder):
    """The switch entry of the pack in `folder`, or None when it has no run."""
    st = wsm.state(folder)
    last = st.get("last_run")
    if not isinstance(last, dict) or not last.get("run"):
        return None
    run = ws / last["run"]
    for name in ("result.json", "report.html"):
        if not (run / name).is_file():
            raise StudioError(f"{run / name} is missing: `terms run` the pack {folder.name} again")
    try:
        digest = json.loads((run / "result.json").read_text(encoding="utf-8"))["x-pack"]["definition_digest"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise StudioError(f"{run / 'result.json'} is not a terms Result: {e}")
    dataset = st.get("dataset")
    if not isinstance(dataset, dict) or not dataset.get("sales_digest"):
        raise StudioError(f"{folder / 'workspace.json'} names no dataset digest: `terms run` the pack {folder.name} over its sales")
    entry = {"pack_id": folder.name, "pack_digest": digest, "page": (run / "report.html").relative_to(ws).as_posix(),
             "shared": {"kind": SHARED_KIND, "digest": dataset["sales_digest"]}}
    title = _title(folder)
    if title:
        entry["title"] = title
    return entry


def build(ws, folder):
    """The studio-view/v0 input whose active pack is the one in `folder`."""
    packs_dir = ws / "packs"
    packs = []
    for sub in sorted(packs_dir.iterdir()) if packs_dir.is_dir() else []:
        if sub.is_dir() and not sub.is_symlink():
            entry = _entry(ws, sub)
            if entry:
                packs.append(entry)
    if not any(p["pack_id"] == folder.name for p in packs):
        raise StudioError(f"the pack {folder.name} has no run yet: `terms run` it, then `terms studio` again")
    table = wsm.read_json(folder / "readiness.json", None)
    if not isinstance(table, dict):
        raise StudioError(f"{folder / 'readiness.json'} is missing: `terms readiness` writes it")
    return {"schema": SCHEMA, "active": folder.name, "packs": packs, "readiness": table,
            "history": wsm.history(folder)}


def render(view, viewer):
    """The page for `view`, drawn by the capsule-viewer build at `viewer`."""
    if not viewer:
        raise StudioError("name a capsule-viewer build that has the Studio page: --viewer DIR or $CAPSULE_VIEWER "
                          "(a directory holding dist/index.js; `npm run build` in capsule-viewer/ts makes one)")
    if not (pathlib.Path(viewer) / "dist" / "index.js").is_file():
        raise StudioError(f"{viewer} holds no dist/index.js: build capsule-viewer first")
    node = shutil.which("node")
    if not node:
        raise StudioError("node is not installed; the Studio page is drawn by capsule-viewer (Node 20 or later)")
    done = subprocess.run([node, str(BRIDGE), str(viewer)], input=json.dumps(view).encode(),
                          capture_output=True, timeout=60)
    if done.returncode != 0:
        raise StudioError("capsule-viewer refused the studio input: " + done.stderr.decode(errors="replace").strip())
    return done.stdout.decode()


_SNAPSHOT = re.compile(r'<code data-snapshot-digest>([0-9a-f]{64})</code></p>'
                       r'<script type="application/json" data-studio-input>(.*?)</script>', re.S)


def snapshot(text):
    """(declared digest, actual digest, input) of a Studio page, or None when `text` is not one."""
    m = _SNAPSHOT.search(text)
    if not m:
        return None
    declared, body = m.groups()
    return declared, hashlib.sha256(body.encode()).hexdigest(), json.loads(body)
