#!/usr/bin/env python3
"""Latitude Health Innovations — admin APPROVAL gate (stage as draft).

Moves a proposal from proposed_articles.json into ../articles.json as a DRAFT
(status="draft"). Drafts are NOT public. publish.py is the actual publish switch:
it promotes a draft to status="published" after a human writes its summary.

  - Approve -> entry copied into ../articles.json as a draft (status="draft").
  - Reject  -> entry archived in rejected.json (and never re-proposed).

Usage:
  python3 approve.py --list                       # show the pending queue
  python3 approve.py --approve 42241742 12345678  # stage these as drafts
  python3 approve.py --reject 42312819            # archive these PMIDs
  python3 approve.py                              # interactive review (a/r/s/q)

After approving: write each study's `summary` (+ confirm tags/type) in
../articles.json, run `publish.py --publish PMID`, then deploy the static files
(index.html, styles.css, articles.json) to GoDaddy. See README.md.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTICLES = HERE.parent / "articles.json"
PROPOSED = HERE / "proposed_articles.json"
REJECTED = HERE / "rejected.json"


def _load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_articles(arts):
    arts["lastUpdated"] = _now()
    ARTICLES.write_text(json.dumps(arts, indent=2, ensure_ascii=False) + "\n")


def _to_study(p):
    return {
        "pmid": p.get("pmid"),
        "title": p.get("title"),
        "authors": p.get("authors", []),
        "journal": p.get("journal"),
        "year": p.get("year"),
        "doi": p.get("doi"),
        "url": p.get("url"),
        "type": p.get("type", "study"),     # auto (PubMed pubtype); editable
        "tags": p.get("tags", []),          # DRAFT tags; confirm/edit before publish
        "summary": "",                       # human-written; REQUIRED to publish
        "status": "draft",                  # the site shows a study ONLY once `summary` is non-empty
        "added": _now(),
    }


def main():
    ap = argparse.ArgumentParser(description="Approve (stage as draft) / reject proposed articles")
    ap.add_argument("--list", action="store_true", help="list the pending queue")
    ap.add_argument("--approve", nargs="*", default=[], metavar="PMID")
    ap.add_argument("--reject", nargs="*", default=[], metavar="PMID")
    args = ap.parse_args()

    prop = _load(PROPOSED, {"proposed": []})
    arts = _load(ARTICLES, {"lastUpdated": None, "studies": []})
    rej = _load(REJECTED, {"rejected": []})
    pending = prop.get("proposed", [])
    by_pmid = {str(p.get("pmid")): p for p in pending}

    if args.list or (not args.approve and not args.reject and sys.stdin.isatty() is False):
        print(f"{len(pending)} pending proposal(s):\n")
        for i, p in enumerate(pending, 1):
            print(f"[{i}] {p.get('pmid')}  ({p.get('year')})  {p.get('journal')}")
            print(f"     {p.get('title')}")
            print(f"     query: {p.get('query')}   {p.get('url')}\n")
        if not args.list:
            print("Use --approve PMID... / --reject PMID..., or run interactively in a terminal.")
        return

    approve_ids = [str(x) for x in args.approve]
    reject_ids = [str(x) for x in args.reject]

    # Interactive review when no explicit ids given
    if not approve_ids and not reject_ids:
        for p in pending:
            print(f"\n{p.get('pmid')} ({p.get('year')}) — {p.get('journal')}\n  {p.get('title')}\n  {p.get('url')}")
            ans = input("  [a]pprove / [r]eject / [s]kip / [q]uit: ").strip().lower()
            if ans == "q":
                break
            if ans == "a":
                approve_ids.append(str(p.get("pmid")))
            elif ans == "r":
                reject_ids.append(str(p.get("pmid")))

    moved_a, moved_r = [], []
    for pid in approve_ids:
        p = by_pmid.get(pid)
        if p and not any(str(s.get("pmid")) == pid for s in arts["studies"]):
            arts["studies"].append(_to_study(p))
            moved_a.append(pid)
    for pid in reject_ids:
        p = by_pmid.get(pid)
        if p:
            p2 = dict(p); p2["status"] = "rejected"; p2["rejected_at"] = _now()
            rej["rejected"].append(p2)
            moved_r.append(pid)

    handled = set(moved_a) | set(moved_r)
    prop["proposed"] = [p for p in pending if str(p.get("pmid")) not in handled]

    if moved_a:
        _save_articles(arts)
    if moved_r:
        REJECTED.write_text(json.dumps(rej, indent=2, ensure_ascii=False) + "\n")
    if handled:
        PROPOSED.write_text(json.dumps(prop, indent=2, ensure_ascii=False) + "\n")

    print(f"\nApproved {len(moved_a)} as DRAFT -> ../articles.json; rejected {len(moved_r)}.")
    if moved_a:
        print("  These stay HIDDEN on the site until you write each study's `summary`.")
        print("  NEXT: in ../articles.json, write a plain-language `summary` (and confirm `tags`/`type`),")
        print("        then deploy index.html + styles.css + articles.json to GoDaddy.")


if __name__ == "__main__":
    main()
