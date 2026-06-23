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

OGE has no per-president index view, so filing URLs are config-driven. A seed list of
known public 278-T filings ships in `president.py`; override or extend it via config:

```yaml
president:
  filer_name: "Donald J. Trump"   # optional (default)
  party: "R"                       # optional (default)
  filings:                         # optional; falls back to the in-code seed list
    - url: "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/<UNID>/$FILE/<file>.pdf"
      disclosure_date: "2026-05-08"   # optional; parsed from the filename if omitted
```

Add new 278-T URLs to config as OGE publishes them (searchable at extapps2.oge.gov;
Quiver's tracker at quiverquant.com/Donald-Trump-Stock-Trades aggregates the same OGE
filings). The `president` step also runs in the daily `refresh_all` sweep.
