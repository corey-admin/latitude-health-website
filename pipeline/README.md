# New-Research pipeline — automated search → admin approval → publish

ASCVD-style **decoupled** pipeline. The public website stays **static** on GoDaddy and
only reads approved content from `../articles.json`. This folder holds the off-site
automation. **Nothing reaches the public site without admin approval.**

```
 search_new_research.py  ──►  proposed_articles.json   (private review queue)
        (automated, scheduled)          │
                                        ▼
                                  approve.py            (admin: approve / reject)
                                        │
                      approved ─────────┼───────── rejected
                                        ▼                 ▼
                              ../articles.json      rejected.json
                            (published feed)        (archive; never re-proposed)
                                        │
                                        ▼
                    upload index.html + styles.css + articles.json → GoDaddy
```

No third-party dependencies — `search_new_research.py` and `approve.py` use only the
Python 3 standard library, so they run on a laptop, a server, or CI.

## The cycle

1. **Search (automated).** Finds newly published studies on heat / light (UV→infrared) and
   cardiovascular health in diverse populations, and writes the private queue:
   ```
   NCBI_EMAIL=you@latitude-health.org python3 search_new_research.py --days 30
   ```
   Already-published, pending, and rejected PMIDs are skipped automatically.

2. **Review & approve (admin — this is the gate).**
   ```
   python3 approve.py --list                      # see the queue
   python3 approve.py --approve 42241742 40012345 # publish these
   python3 approve.py --reject  42312819          # archive these
   python3 approve.py                             # interactive (a/r/s/q)
   ```
   Approved entries are copied into `../articles.json`; rejected ones go to `rejected.json`.

3. **Write the summary (this is the publish switch).** Approved studies are added to
   `../articles.json` as **drafts** and stay **hidden on the site until you fill their
   `summary`** (one or two sentences in your own words). Also confirm the auto-filled `type`
   (RCT / cohort / review / …) and the draft `tags` (heat / UV / infrared / BP / CVD / equity).
   Citations are real PubMed records — never invented; summaries are always human-written.

4. **Publish.** Upload **`index.html`, `styles.css`, and `articles.json`** to GoDaddy
   `public_html` (File Manager or FTP). The site renders the updated feed. *(Only `articles.json`
   changes between routine updates.)*

## Scheduling the search (the "automated" part)

GoDaddy static hosting can't run the search — schedule it where Python + network are available:

- **GitHub Action (recommended — no server, gives you a PR to review):** a scheduled workflow
  runs the search and commits `proposed_articles.json` (or opens a PR). Reviewing the PR *is*
  the approval step. Sketch:
  ```yaml
  # .github/workflows/new-research.yml
  on:
    schedule: [{ cron: "0 13 * * 1" }]   # Mondays 13:00 UTC
    workflow_dispatch:
  jobs:
    search:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - run: python3 pipeline/search_new_research.py --days 14
          env: { NCBI_EMAIL: ${{ secrets.NCBI_EMAIL }} }
        - uses: peter-evans/create-pull-request@v6
          with: { title: "New research candidates", branch: "new-research-queue" }
  ```
- **cron (a machine that stays on):**
  ```
  0 7 * * 1  cd /path/to/pipeline && NCBI_EMAIL=you@org python3 search_new_research.py --days 14
  ```

## Tuning precision

The automated search casts wide and is deliberately noisy — **the approval gate is the real
filter.** To reduce noise, edit `QUERIES` in `search_new_research.py` (e.g. append
`AND humans[Filter]`, exclude basic-science terms), or lower `--max` / `--days`. An optional
`NCBI_API_KEY` env var raises the NCBI rate limit.

## Integrity guarantees
- Only **real PubMed records** (PMID + DOI) ever enter the queue — no fabricated articles.
- **Nothing is published without a human approving it** (`approve.py` / PR merge).
- Summaries are **written by your team**, not auto-generated.
