# congress-trades

Congressional trade tracker. Extracted from the `whitehouse-rke2` monorepo.

- **`app/`** — FastAPI backend + ingest pipelines (the image the cronjobs run).
- **`ui/`** — React frontend.

CI builds multi-arch (amd64+arm64) images on push to `main` and runs the app's
test suite:
- `ghcr.io/robertdwhite/congress-app`
- `ghcr.io/robertdwhite/congress-ui`

Kubernetes manifests (deployments, services, ~17 cronjobs, HTTPRoutes) live in
whitehouse-rke2 and pin a specific digest.

## Presidential trades (STOCK Act)

The President files transaction disclosures with the U.S. Office of Government Ethics
(OGE Form 278-T) rather than the House/Senate eFD systems, so `ingest/president.py`
pulls them separately and stores them as a normal member (`Donald J. Trump`,
`chamber="executive"`). Reports are periodic and broad-range (amounts are `$` brackets),
not real-time like Congress. OGE publishes scanned PDFs with an OCR text layer; we
extract with `pdftotext` (OCR fallback) and parse the transactions table.

New filings are **auto-discovered** from the White House disclosures page
(`whitehouse.gov/disclosures/` — the only public, enumerable index; OGE's Domino views
hide the President and full-text search is disabled there), so a new PTR is picked up on
the next run with no config change. That page serves raw scans with no usable text layer,
so parsing them relies on the OCR fallback (`ocr.enabled`); the extapps2.oge.gov copies of
the same filings carry an Acrobat OCR text layer and are used as the seed list. The parser
gates rows hard (fixed OGE amount brackets, required transaction type, merged-row and
header-noise filters), so a badly scanned filing yields nothing rather than junk and is
marked `paper` once OCR has been tried (clear `parse_status` to re-attempt after parser
improvements).

```yaml
president:
  filer_name: "Donald J. Trump"   # optional (default)
  party: "R"                       # optional (default)
  discover: true                   # optional; poll whitehouse.gov/disclosures for new PTRs
  discover_url: "https://www.whitehouse.gov/disclosures/"   # optional override
  filings:                         # optional; falls back to the in-code seed list
    - url: "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/<UNID>/$FILE/<file>.pdf"
      disclosure_date: "2026-05-08"   # optional; parsed from the filename if omitted
```

Presidential trades flow through the same downstream steps as congressional ones:
`ticker_aliases` maps equity/issuer names to tickers (bond rows are tagged
`asset_type: bond`), which lights up returns, signals, and alert rules automatically.
"Real-time" here is bounded by the disclosure regime itself — 278-T filings are periodic
(30–45 day windows, sometimes late) — so freshness = polling cadence of the `president`
step (the daily `refresh_all` sweep, plus any dedicated CronJob in whitehouse-rke2).
