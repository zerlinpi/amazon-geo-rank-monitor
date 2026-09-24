# Amazon Geo Rank Monitor

Amazon geographic organic-rank monitoring service. It observes the same Amazon keyword from multiple geographic profiles, locates one or more ASINs in each SERP, and calculates a weighted organic rank.

## Scope

This repository is intentionally focused on Amazon rank monitoring. Amazon Ads bidding, listing optimization, inventory, repricing, and review scraping are out of scope.

The architecture uses a Hybrid provider model:

- **Managed monitoring:** Oxylabs Amazon Search for routine, structured SERP collection.
- **Strict verification:** a later phase adds browser + residential proxy verification where the requested IP geography and Amazon Deliver-to location are independently verified.

Managed mode must not be described as strict IP verification. The Oxylabs adapter records the requested IP geography as metadata while using the delivery postal code for the managed Amazon search geography.

## Rank semantics

The system keeps three concepts separate:

- `organic_rank`: position among organic products only; this drives the weighted score.
- `absolute_rank`: observed overall product position when the provider exposes a combined sequence.
- `sponsored_rank`: position in sponsored results when present.

If an ASIN is not found within `search_depth`, the stored values are:

```text
found = false
organic_rank = null
effective_rank = search_depth + 1
```

A provider failure is an error, not an ASIN-not-found result.

## One SERP, many ASINs

The billable/data-collection unit is a SERP probe, not an ASIN. A single query for:

```text
marketplace + keyword + geo profile + device + search depth
```

is matched against every requested ASIN. Therefore 2 ASINs across 3 geographic profiles require 3 provider probes, not 6.

## Weighted rank

For successful observations:

```text
weighted_rank = sum(effective_rank_i * weight_i) / sum(weight_i)
```

Weights are normalized mathematically and do not need to sum to 1 or 100. The raw regional observations are always retained alongside the weighted score.

## Local development

Requirements: Python 3.12+.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp ../.env.example ../.env
PYTHONPATH=src python -m pytest -q
ruff check src tests
```

Configure geographic profiles from `config/geo_profiles.example.yaml`.

For real Oxylabs calls set:

```env
OXYLABS_USERNAME=...
OXYLABS_PASSWORD=...
```

No provider credentials are required to import the package or run the offline unit tests.

## Current implementation phase

The current phase contains the provider-neutral rank core, Oxylabs managed adapter, weighted-rank logic, SQLite-compatible persistence, and orchestration. Strict browser verification, REST/MCP exposure, prepaid credits/Stripe, and the Fantastic Admin SaaS UI are implemented in later isolated phases described in `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`.
