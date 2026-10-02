# Marketplace

This directory holds official, installable MP22 sample packages for OpenAgent.
Each sample is a real `openagent-package` bundle (see `docs/packages/`) that
installs through the package API — not a mock listing.

## Samples

- `packages/research_workforce/` — manager-led research team (research,
  browser and report agents + research pipeline workflow)
- `packages/swe_workforce/` — planner/coder/tester/reviewer team wired to the
  Code Agent and Sandbox with merge approvals
- `packages/marketing_workforce/` — research/content/SEO/analytics team with
  publish approval

Each directory contains:

```
manifest.json                        # canonical package manifest
<id>.openagent-package.json          # portable bundle ({files} map + integrity)
```

## Validate / install a sample

```bash
python scripts/openagent_package.py validate marketplace/packages/research_workforce
python scripts/openagent_package.py inspect marketplace/packages/research_workforce/openagent.research-workforce-1.0.0.openagent-package.json
```

Import through the API (`POST /api/v1/organizations/{id}/packages/import`)
or the Template Center, then install via the installation wizard. Execution
always flows through the existing Agent Runtime, Workflow Engine, Tool
Runtime, Model Router, Memory, Browser/Code/Sandbox and approval systems.

## Package format

Documented in `docs/packages/manifest-spec.md`. Ratings, reviews, payments
and subscriptions are deferred to the marketplace commerce phase (MP23);
this directory deliberately contains no commerce logic.

See the main [CONTRIBUTING.md](../CONTRIBUTING.md) for development guidelines.
