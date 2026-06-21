#!/usr/bin/env python3
"""Latitude Health Innovations — PUBLISH gate (the real publish switch).

Three states: proposed (search) -> draft (approve.py) -> published (here).
The public site renders ONLY studies with status == "published". This step
refuses to publish a study unless it has a human-written `summary` and a
confirmed `type` and at least one `tag` — so nothing half-finished goes live.

Usage:
  python3 publish.py --list                  # drafts pending publish + what's missing
  python3 publish.py --publish 42241742      # validate, then set status=published
  python3 publish.py --unpublish 42241742    # revert to draft (pull from the site)
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ARTICLES = Path(__file__).resolve().parent.parent / "articles.json"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _missing(s):
    miss = []
    if not (s.get("summary") and str(s.get("summary")).strip()):
        miss.append("summary")
    if not (s.get("type") and str(s.get("type")).strip()):
        miss.append("type")
    if not (s.get("tags") or []):
        miss.append("tags")
    return miss


def main():
    ap = argparse.ArgumentParser(description="Promote approved drafts to published (validated)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--publish", nargs="*", default=[], metavar="PMID")
    ap.add_argument("--unpublish", nargs="*", default=[], metavar="PMID")
    args = ap.parse_args()

    if not ARTICLES.exists():
        print("articles.json not found", file=sys.stderr)
        sys.exit(1)
    data = json.loads(ARTICLES.read_text())
    studies = data.get("studies", [])
    by_pmid = {str(s.get("pmid")): s for s in studies}

    if args.list or (not args.publish and not args.unpublish):
        drafts = [s for s in studies if s.get("status") != "published"]
        pub = [s for s in studies if s.get("status") == "published"]
        print(f"{len(pub)} published, {len(drafts)} draft(s) pending publish:\n")
        for s in drafts:
            miss = _missing(s)
            flag = "READY" if not miss else "needs: " + ", ".join(miss)
            print(f"  {s.get('pmid')}  [{flag}]  {(s.get('title') or '')[:70]}")
        if drafts:
            print("\n  Fill missing fields in articles.json, then: python3 publish.py --publish PMID")
        return

    changed = False
    for pid in [str(x) for x in args.publish]:
        s = by_pmid.get(pid)
        if not s:
            print(f"  ! {pid}: not found", file=sys.stderr); continue
        miss = _missing(s)
        if miss:
            print(f"  ✗ {pid}: REFUSED — missing {', '.join(miss)} (write them in articles.json first)")
            continue
        s["status"] = "published"; s["published_at"] = _now(); changed = True
        print(f"  ✓ {pid}: published")
    for pid in [str(x) for x in args.unpublish]:
        s = by_pmid.get(pid)
        if s:
            s["status"] = "draft"; s.pop("published_at", None); changed = True
            print(f"  ↩ {pid}: unpublished (back to draft)")

    if changed:
        data["lastUpdated"] = _now()
        ARTICLES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print("\n  Deploy index.html + styles.css + articles.json to GoDaddy to go live.")


if __name__ == "__main__":
    main()
