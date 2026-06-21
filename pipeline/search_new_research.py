#!/usr/bin/env python3
"""Latitude Health Innovations — automated New-Research search (PROPOSAL generator).

ASCVD-style decoupled pipeline. SEARCHES PubMed for newly published studies on
heat / light (ultraviolet -> infrared) and cardiovascular health in diverse
populations, and writes a PRIVATE proposals queue (proposed_articles.json).

It NEVER touches the public site, and it NEVER writes a public summary (summaries
are human-written at approval time). An admin reviews + approves with approve.py;
only approved items with a human summary are shown on the static site.

Stdlib only (urllib) -> no dependencies; runs anywhere (cron, GitHub Action, laptop).

Usage:
  python3 search_new_research.py                 # last 120 days, default queries
  python3 search_new_research.py --days 14 --max 8
  NCBI_EMAIL=you@org python3 search_new_research.py   # polite contact (recommended)
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE_ROOT = HERE.parent
ARTICLES = SITE_ROOT / "articles.json"
PROPOSED = HERE / "proposed_articles.json"
REJECTED = HERE / "rejected.json"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "latitude-health-newresearch"

# Topic queries: heat and/or light (UV->IR) x cardiovascular x (often) diverse populations.
QUERIES = [
    ("Sauna & heat → cardiovascular",
     '(sauna OR "heat therapy" OR hyperthermia OR "passive heat" OR "thermal therapy") '
     'AND ("blood pressure" OR cardiovascular OR vascular OR hypertension OR endothelial)'),
    ("Infrared / light therapy → cardiovascular",
     '(infrared OR "near-infrared" OR photobiomodulation OR "red light" OR "light therapy") '
     'AND ("blood pressure" OR cardiovascular OR vascular OR endothelial OR "nitric oxide")'),
    ("UV / sunlight → cardiovascular health",
     '(ultraviolet OR "UV exposure" OR sunlight OR "solar radiation") '
     'AND ("blood pressure" OR cardiovascular OR "nitric oxide" OR hypertension)'),
    ("Heat/light & diverse populations",
     '(sauna OR heat OR ultraviolet OR infrared OR sunlight) AND (cardiovascular OR "blood pressure") '
     'AND (race OR ethnicity OR "skin pigmentation" OR disparities OR "diverse population" OR latitude)'),
]

# Precision guards appended to every query. Human studies only; exclude the
# basic-science / nanomedicine / device noise that swamps these keywords.
FILTER = ('humans[Filter] NOT (nanoparticle*[tiab] OR nanocomposite*[tiab] OR nanorobot*[tiab] '
          'OR photothermal[tiab] OR "drug delivery"[tiab] OR robot*[tiab] OR surgical[tiab] '
          'OR surgery[tiab] OR wound[tiab] OR fluorescence[tiab] OR hydrogel[tiab] OR krill[tiab] '
          'OR infertility[tiab] OR catalysis[tiab] OR nanozyme*[tiab] OR ablation[tiab] OR melasma[tiab] '
          'OR hyperscanning[tiab] OR thyroid[tiab] OR propranolol[tiab] OR berberine[tiab] '
          'OR moxibustion[tiab] OR nomogram[tiab] OR rejuvenation[tiab] '
          # measurement/imaging, materials chemistry, and off-mission disease noise that the
          # infrared/UV queries otherwise pull (spectroscopy != light *exposure*):
          'OR spectroscopy[tiab] OR spectrometry[tiab] OR chemometrics[tiab] OR stabilizer*[tiab] '
          'OR "stem cell"[tiab] OR "multiple sclerosis"[tiab] OR "skin cancer"[tiab] '
          # infrared/UV terms are heavily used in diagnostics/therapeutics unrelated to light EXPOSURE:
          'OR imaging[tiab] OR photodynamic[tiab] OR "intense pulsed light"[tiab] OR microparticle*[tiab])')

# PubMed publication types -> our coarse study-type label (auto-filled; admin may edit).
TYPE_MAP = [
    ("Meta-Analysis", "meta-analysis"),
    ("Systematic Review", "systematic review"),
    ("Randomized Controlled Trial", "RCT"),
    ("Clinical Trial", "trial"),
    ("Observational Study", "cohort"),
    ("Review", "review"),
    ("Comparative Study", "study"),
]

# Draft topic tags inferred from query label + title (admin confirms/edits before publish).
TAG_RULES = [
    ("heat", ("sauna", "heat", "hyperthermia", "thermal")),
    ("UV", ("ultraviolet", "uv ", "sunlight", "solar")),
    ("infrared", ("infrared", "photobiomodulation", "red light")),
    ("BP", ("blood pressure", "hypertension", "hypertensive")),
    ("CVD", ("cardiovascular", "heart", "vascular", "endothelial", "cardiac")),
    ("equity", ("race", "ethnic", "disparit", "diverse", "pigmentation", "latitude", "socioeconomic")),
]


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": TOOL})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _common():
    p = {"tool": TOOL}
    if os.environ.get("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    if os.environ.get("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    return p


def esearch(query, days, retmax):
    term = f"({query}) AND {FILTER}"
    p = {"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax),
         "datetype": "pdat", "reldate": str(days), "sort": "date", **_common()}
    d = json.loads(_get(f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(p)}"))
    return d.get("esearchresult", {}).get("idlist", [])


def esummary(pmids):
    if not pmids:
        return {}
    p = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json", **_common()}
    d = json.loads(_get(f"{EUTILS}/esummary.fcgi?{urllib.parse.urlencode(p)}"))
    return d.get("result", {})


def known_pmids():
    seen = set()
    for path, keys in ((ARTICLES, ("studies",)), (PROPOSED, ("proposed",)), (REJECTED, ("rejected",))):
        if path.exists():
            try:
                d = json.loads(path.read_text())
                for k in keys:
                    for it in (d.get(k) or []):
                        if isinstance(it, dict) and it.get("pmid"):
                            seen.add(str(it["pmid"]))
            except Exception:
                pass
    return seen


def doi_of(s):
    for aid in s.get("articleids", []):
        if aid.get("idtype") == "doi":
            return aid.get("value")
    return None


def study_type(s):
    pts = [str(x) for x in (s.get("pubtype") or [])]
    for needle, label in TYPE_MAP:
        if any(needle.lower() in pt.lower() for pt in pts):
            return label
    return "study"


def draft_tags(label, title):
    text = (label + " " + (title or "")).lower()
    return [tag for tag, kws in TAG_RULES if any(k in text for k in kws)]


def main():
    ap = argparse.ArgumentParser(description="PubMed search -> proposed_articles.json (no publishing)")
    ap.add_argument("--days", type=int, default=120, help="recency window (published within N days)")
    ap.add_argument("--max", type=int, default=6, help="max results per query")
    args = ap.parse_args()

    seen = known_pmids()
    existing = []
    if PROPOSED.exists():
        try:
            existing = json.loads(PROPOSED.read_text()).get("proposed", [])
        except Exception:
            existing = []
    pending = {str(x.get("pmid")) for x in existing}

    new = []
    for label, q in QUERIES:
        try:
            ids = esearch(q, args.days, args.max)
        except Exception as e:
            print(f"  ! query failed [{label}]: {e}", file=sys.stderr)
            continue
        ids = [i for i in ids if i not in seen and i not in pending]
        time.sleep(0.4)
        res = esummary(ids) if ids else {}
        for pmid in ids:
            s = res.get(pmid)
            if not isinstance(s, dict):
                continue
            title = (s.get("title") or "").rstrip(".")
            new.append({
                "pmid": pmid,
                "title": title,
                "authors": [a.get("name") for a in s.get("authors", []) if a.get("name")][:3],
                "journal": s.get("fulljournalname") or s.get("source"),
                "year": (s.get("pubdate", "")[:4] or None),
                "doi": doi_of(s),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "type": study_type(s),         # auto from PubMed pubtype (metadata, not interpretation)
                "tags": draft_tags(label, title),  # DRAFT — admin confirms before publish
                "query": label,
                "status": "proposed",
            })
            pending.add(pmid)
        time.sleep(0.4)

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": args.days,
        "queries": [l for l, _ in QUERIES],
        "proposed": existing + new,
    }
    PROPOSED.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"Found {len(new)} new candidate(s); {len(out['proposed'])} total pending in {PROPOSED.name}.")
    for x in new[:25]:
        print(f"  + [{x['type']}] {x['pmid']} {x['tags']}: {x['title'][:72]}")
    if not new:
        print("  (no new candidates this run)")
    print("\nNext: review with  python3 approve.py --list  then approve/reject.")
    print("Approved studies stay hidden until a human writes their `summary` in ../articles.json.")


if __name__ == "__main__":
    main()
