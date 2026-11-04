#!/usr/bin/env python3
"""Read a seller's deal store into the sales scripts/evaluators/sticker_deal.py folds.

The shapes are evidencebook-deal's (testdata/studio/README.md, PR 142): `capsulectl
--profile deal deal list --json` names the closed deals (kind "deal"), and
`deal export --deal ID --output FILE` writes a JSON array of sealed records, each
with `at` (or `x-deal-v0.at`), `type` and `body`. Per deal:

    offered_price   the last action-record/v0 {action: "offer"} amount_minor
    accepted_price  the action-record/v0 {action: "commit"} amount_minor; on a
                    deal with no commit record, the action-outcome/v0
                    unchecked_action's attempted commit amount_minor (the price
                    the seller tried to charge, so a changed price is a miss
                    and not "not evaluable")
    paid_at         `at` of the evidence record with source x402_settle_response
    delivered_at    `at` of the evidence record with source seller_handoff

A fact the records do not carry stays absent, and the fold reports not_evaluable.
"""
import json
import os
import pathlib
import subprocess


class StoreError(Exception):
    """A refusal, said in words."""


def _at(rec):
    at = rec.get("at")
    if at is None and isinstance(rec.get("x-deal-v0"), dict):
        at = rec["x-deal-v0"].get("at")
    return at


def _amount(body):
    v = body.get("amount_minor") if isinstance(body, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def sale_from_records(deal_id, records):
    """One normalized sale from a deal's exported records."""
    if not isinstance(records, list):
        raise StoreError(f"deal {deal_id}: the export is not a JSON array of records")
    sale = {"deal_id": deal_id}
    attempted = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        body = rec.get("body") if isinstance(rec.get("body"), dict) else {}
        kind = rec.get("type")
        if kind == "action-record/v0":
            if body.get("action") == "offer" and _amount(body) is not None:
                sale["offered_price"] = _amount(body)
            elif body.get("action") == "commit" and _amount(body) is not None:
                sale["accepted_price"] = _amount(body)
        elif kind == "action-outcome/v0" and body.get("status") == "unchecked_action":
            att = body.get("attempted")
            if isinstance(att, dict) and att.get("action") == "commit" and _amount(att) is not None:
                attempted = _amount(att)
        elif kind == "evidence":
            if body.get("source") == "x402_settle_response" and _at(rec):
                sale["paid_at"] = _at(rec)
            elif body.get("source") == "seller_handoff" and _at(rec):
                sale["delivered_at"] = _at(rec)
    if "accepted_price" not in sale and attempted is not None:
        sale["accepted_price"] = attempted
    return sale


def sales_from_exports(directory):
    """Sales from a directory of `deal export` files, one per deal, named <deal id>.json."""
    d = pathlib.Path(directory)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        raise StoreError(f"{directory} holds no deal exports (*.json, one per deal, from `deal export`)")
    sales = []
    for f in files:
        try:
            records = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            raise StoreError(f"cannot read {f}: {e}")
        sales.append(sale_from_records(f.stem, records))
    return sales


def sales_from_store(home, profile="deal", capsulectl="capsulectl", run=subprocess.run, tmp=None):
    """Sales from a live store: `deal list --json`, then `deal export` per closed deal.
    `home` is the store's XDG_HOME (the replay script's SELLER_XDG_HOME)."""
    env = dict(os.environ, XDG_CONFIG_HOME=str(home), XDG_DATA_HOME=str(home), XDG_STATE_HOME=str(home))
    base = [capsulectl, "--profile", profile, "deal"]

    def call(args):
        p = run(base + args, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        if p.returncode != 0:
            raise StoreError(f"{' '.join(base + args)} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout

    try:
        listing = json.loads(call(["list", "--json"]))
    except ValueError as e:
        raise StoreError(f"deal list --json is not JSON: {e}")
    items = listing.get("deals", listing) if isinstance(listing, dict) else listing
    ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("kind") == "deal"
           and (i.get("status") in (None, "closed"))]
    if not ids:
        raise StoreError(f"{home} holds no closed deals")
    tmpdir = pathlib.Path(tmp) if tmp else pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
    sales = []
    for did in ids:
        out_file = tmpdir / f"terms-export-{did}.json"
        call(["export", "--deal", did, "--output", str(out_file)])
        try:
            sales.append(sale_from_records(did, json.loads(out_file.read_text())))
        finally:
            out_file.unlink(missing_ok=True)
    return sales
