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
