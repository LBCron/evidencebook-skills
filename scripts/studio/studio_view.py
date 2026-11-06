"""The Studio page of a Terms Pack workspace (evidencebook-skills#143, capsule-viewer#291).

`build(ws, folder)` makes the `studio-view/v0` input (capsule-viewer docs/design/studio-page.md
section 2) from files `terms` verbs already wrote, and from nothing else (the pack's title is read from its pack-source.yaml):

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


def _title(ws, folder):
    source = folder / "pack-source.yaml"
    if not source.exists():
        return None
    try:
        title = yaml.safe_load(_within(ws, source).read_text(encoding="utf-8")).get("title")
    except (OSError, yaml.YAMLError, AttributeError, StudioError):
        return None
    # the renderer refuses a title over 200 characters, and one pack's title must not block every pack's page
    return title if isinstance(title, str) and 0 < len(title) <= 200 else None


def _within(ws, path):
    """`path` resolved, which must sit inside the workspace: a link out is refused, so the page is built from the workspace only."""
    resolved = path.resolve()
    if resolved != ws and ws not in resolved.parents:
        raise StudioError(f"{path} leads outside the workspace {ws}; refusing to read it")
    return resolved


def _entry(ws, folder):
    """The switch entry of the pack in `folder`, or None when it has no run."""
    if (folder / "workspace.json").exists():
        _within(ws, folder / "workspace.json")
    st = wsm.state(folder)
    last = st.get("last_run") if isinstance(st, dict) else None
    if not isinstance(last, dict) or not last.get("run"):
        return None
    if not isinstance(last["run"], str):
        raise StudioError(f"{folder / 'workspace.json'} names a last run that is not a folder: `terms run` the pack {folder.name} again")
    run = _within(ws, ws / last["run"])
    for name in ("result.json", "report.html"):
        if (run / name).exists():
            _within(ws, run / name)
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
    title = _title(ws, folder)
    if title:
        entry["title"] = title
    return entry


def build(ws, folder, current_digest=None):
    """The studio-view/v0 input whose active pack is the one in `folder`. `current_digest` is the pack
    digest of the source as it is now: the readiness table and history describe it, so the latest run
    must be a run of it, or the loop would show an edited pack as already tried."""
    ws = ws.resolve()
    folder = _within(ws, folder)
    packs_dir = ws / "packs"
    packs = []
    for sub in sorted(packs_dir.iterdir()) if packs_dir.is_dir() else []:
        if sub.is_dir() and not sub.is_symlink():
            entry = _entry(ws, sub)
            if entry:
                packs.append(entry)
    if not any(p["pack_id"] == folder.name for p in packs):
        raise StudioError(f"the pack {folder.name} has no run yet: `terms run` it, then `terms studio` again")
    active = next(p for p in packs if p["pack_id"] == folder.name)
    if current_digest is not None and active["pack_digest"] != current_digest:
        raise StudioError(f"{folder.name} has changed since its last run: `terms run` it, then `terms studio` again")
    for name in ("readiness.json", "history.jsonl"):
        if (folder / name).exists():
            _within(ws, folder / name)
    table = wsm.read_json(folder / "readiness.json", None)
    if not isinstance(table, dict):
        raise StudioError(f"{folder / 'readiness.json'} is missing: `terms readiness` writes it for a pack `terms init` made")
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
    try:
        done = subprocess.run([node, str(BRIDGE), str(viewer)], input=json.dumps(view).encode(),
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise StudioError(f"capsule-viewer at {viewer} did not draw the page: {e}")
    err = done.stderr.decode(errors="replace").strip()
    if done.returncode == 2:  # the bridge's own: StudioViewRefused, said in words
        raise StudioError("capsule-viewer refused the studio input: " + err)
    if done.returncode != 0:
        raise StudioError(f"capsule-viewer at {viewer} could not draw the page: {err[:500]}")
    page = done.stdout.decode()
    if snapshot(page) is None or snapshot(page)[2] is None:
        raise StudioError(f"capsule-viewer at {viewer} drew a page without the studio snapshot; it is not a build this verb reads")
    return page


_SNAPSHOT = re.compile(r'<code data-snapshot-digest>([0-9a-f]{64})</code></p>'
                       r'<script type="application/json" data-studio-input>(.*?)</script>', re.S)


def snapshot(text):
    """(declared digest, actual digest, input or None) of a Studio page, or None when `text` is not one.
    The input is None when the embedded JSON is not an object."""
    m = _SNAPSHOT.search(text)
    if not m:
        return None
    declared, body = m.groups()
    try:
        view = json.loads(body)
    except ValueError:
        view = None
    return declared, hashlib.sha256(body.encode()).hexdigest(), view if isinstance(view, dict) else None
