# HubSpot → PostgreSQL pipeline

[![pipeline](https://github.com/giselleevita/hubspot-pipeline/actions/workflows/pipeline.yml/badge.svg)](https://github.com/giselleevita/hubspot-pipeline/actions/workflows/pipeline.yml)

This project incrementally extracts HubSpot contacts, companies, deals, and their many-to-many associations into PostgreSQL, then uses dbt to produce typed staging views and query-ready GTM marts. It is a small but production-shaped example of the system behind questions such as “which institutions have active opportunities, who is involved, and how much pipeline was created by stage?”

**What this shows:** incremental extraction against a live API, watermarks written only after a successful load, idempotent upserts, many-to-many association modelling, PostgreSQL and dbt, 25 unit tests and 22 dbt tests in CI. Verified against a seeded test portal: 62 companies, 242 contacts, 120 deals, 1,171 association rows.

```text
HubSpot API
  ├─ raw objects (source-faithful JSONB)
  └─ raw associations (authoritative relationship edges)
       └─ typed staging views
            ├─ dim_contact
            ├─ dim_company
            ├─ fct_deal ──> fct_deal_stage_daily
            └─ bridge_{deal_contact, deal_company, contact_company}
```

The fact table grain is one row per HubSpot deal because a deal is the unit whose value and stage the commercial team measures. Associations are separate bridge tables because forcing multiple contacts or companies into one foreign key silently loses information. Contact and company are current-state (Type 1) dimensions: changed emails or names overwrite the prior value. If historical attributes mattered, for example attributing pipeline to the company segment at the time of creation, I would add effective dates and current-row flags as Type 2 dimensions.

I chose a conservative high-watermark: each object watermark is the run start, written only after its upserts commit, and every run re-reads a five minute overlap before it. Records changed during a run, and records whose changes had not yet reached the search index when the run started, are therefore eligible again next time. Primary-key upserts make that overlap free. At higher volume I would stream pages into batched inserts rather than holding one object page set in memory.

Two API details cost more than the rest of the extractor put together. Contacts answer to `lastmodifieddate` while companies and deals answer to `hs_lastmodifieddate`, and filtering contacts on the wrong one does not fail, it returns zero results, so an incremental run would have quietly stopped seeing contact changes after the first load. `stg_hubspot__contacts` now carries a `not_null` test on `modified_at_utc`, which is what turns that class of mistake into a failing build. The search endpoint also refuses to page past 10,000 results, so incremental queries sort ascending by modification time and re-anchor on the last record seen instead of stopping there.

Associations are read through the v4 batch endpoint, 100 objects per call, rather than one call per object per association type. Objects that come back with no associations still matter: their rows are deleted before insert, because a link removed in HubSpot has no row to update and would otherwise survive forever.

This version does not handle schema-drift detection, source object deletions, association history, or true deal-stage snapshots. `fct_deal_stage_daily` groups current deals by creation date and current stage; reconstructing stage-as-of-day requires HubSpot property history. It also uses single-node PostgreSQL rather than AWS-managed storage and compute. At Famly scale I would land immutable batches in S3, orchestrate with a managed scheduler, add explicit contracts and freshness alerts, and publish marts through atomic swaps.

## Run it

```bash
cp .env.example .env
# Put a HubSpot private-app token in .env
docker compose up -d postgres
docker compose --profile run run --rm pipeline
```

Use `docker compose --profile run run --rm -e FULL_REFRESH=true pipeline` for an intentional backfill. Normal scheduled runs use per-object high-watermarks.

Run unit tests locally with `python -m pytest -q`: 25 tests covering pagination, the per-object modification property, re-anchoring at the search cap, retry and backoff, the lookback window, the association delete-before-insert rule, and the shape of the demo dataset itself. None of them need a network or a database. `dbt build` runs 13 models and 22 tests. Inspect `pipeline_runs` for start and end time, status, extracted row counts, and errors. A run that loads nothing prints a warning and, with `FAIL_ON_EMPTY_RUN=true`, exits non-zero.

### Data to run it against

Two ways, and neither of them is "trust the screenshot".

**Without a HubSpot token.** `python -m scripts.load_fixture` generates 60 companies, 240 contacts and 120 deals and writes them straight into the raw layer of a separate `hubspot_demo` database, then `dbt build --project-dir dbt --profiles-dir dbt --target demo` builds every model over them. Separate database, because generated rows must never mix with records extracted from a real portal.

**With one.** `python -m scripts.seed_demo --dry-run` shows what would be created; without the flag it pushes the same dataset into a test portal in batches of 100. It needs `crm.objects.{contacts,companies,deals}.write` on the private app, which the pipeline itself never uses, so add the scopes, seed, and remove them again. HubSpot sets creation timestamps itself, so seeded records all carry today's created date; the fixture path keeps the full eighteen month spread.

The dataset is deliberate rather than uniform. It contains deals attached to two companies, deals with no contact, contacts with no company, and deals with no amount, because those are the cases the model claims to handle and a uniform fixture would let all four go untested.

## What the marts answer

`analytics/gtm_questions.sql` holds the five questions this exists to answer. Against the generated dataset:

```text
      deal_stage       | deals | pipeline_value | avg_deal_value | deals_missing_amount
-----------------------+-------+----------------+----------------+----------------------
 appointmentscheduled  |    36 |      916500.00 |          25458 |                    0
 qualifiedtobuy        |    28 |      637000.00 |          23593 |                    1
 closedwon             |    13 |      410000.00 |          31538 |                    0
 presentationscheduled |    20 |      314750.00 |          19672 |                    4
 closedlost            |    10 |      295750.00 |          29575 |                    0
 decisionmakerboughtin |    13 |      271250.00 |          22604 |                    1
```

The other four: pipeline created per month, accounts ranked by open pipeline through the bridge, accounts holding deals with nobody attached, and how often a deal is shared between companies. That last one is the number that decides whether the bridge table earns its place. Here it is 8 deals out of 120, which is the difference between a correct answer and a quietly wrong one for those eight.

## What a run actually looks like

Against a test portal seeded with 60 companies, 240 contacts, 120 deals and 575 association edges, with the lookback shortened to a minute so the behaviour is visible in one sitting:

```text
started_at             status    object_counts
2026-08-31 14:23:57    success   {"companies": 62, "contacts": 242, "deals": 120}   full refresh
2026-08-31 14:25:12    success   {"companies": 61, "contacts": 235, "deals": 120}
2026-08-31 14:26:30    success   {"companies": 56, "contacts": 24,  "deals": 120}
2026-08-31 14:27:15    success   {"companies": 0,  "contacts": 0,   "deals": 0}     warning raised
```

Two things in that table are worth more than the fact that it ran.

The counts decay rather than dropping to zero at once, because each run re-reads its lookback window and the records were written minutes earlier. That is the overlap doing its job, and the upserts are what make it cost nothing.

The deals stay at 120 for two runs after the seed. HubSpot recalculates deal properties asynchronously after a write, and that recalculation bumps `hs_lastmodifieddate` a couple of minutes later, so those deals genuinely had changed. An incremental run immediately after a bulk change re-reading everything is the source behaving normally, not the watermark failing, and it is the sort of thing that looks like a bug at 9am if nobody wrote it down.

The last run loaded nothing, printed the warning, and would have exited non-zero under `FAIL_ON_EMPTY_RUN`.

See [docs/DESIGN.md](docs/DESIGN.md) for the dbt dependency graph and the reasoning behind grain, watermarking, and the two HubSpot API quirks that cost the most engineering time.

## Design answers

- Raw JSON preserves source fidelity and makes transformation changes replayable without calling HubSpot again.
- Upsert by HubSpot object ID makes repeated windows idempotent. Advancing a watermark before a successful load could permanently skip records.
- Staging views keep typing and renaming transparent; marts are tables because they are stable, consumer-facing query surfaces.
- The selected fields support the marts. Unused HubSpot metadata remains available in raw JSON rather than widening every model.
- If extraction succeeds but dbt fails, raw data and watermarks are committed while the previous mart tables remain. The failed command and `pipeline_runs` status make the run visible; production would add atomic mart swaps and notifications.

## Why this is a GTM system, not a demo script

- Sales and Marketing get stable, documented entities rather than querying CRM-shaped JSON.
- Finance can reason about deal value at an explicit grain without double-counting multi-contact relationships.
- Customer Success and Product can join institutions and people through maintained bridge tables.
- Retries, overlapping watermarks, primary-key upserts, CI tests, and run logs turn a one-off integration into an operable system.
- Raw source fidelity keeps debugging friendly: a non-technical stakeholder’s HubSpot record can be traced through every layer.

## Operational checks

```sql
select status, object_counts, started_at, ended_at, error_message
from pipeline_runs order by started_at desc;
```

A failed status is actionable immediately. An all-zero successful run emits a warning and should page only after considering expected source activity. Re-run safety comes from object-key upserts and composite association keys; the watermark advances only after the object transaction succeeds.

## Licence

Copyright (c) 2026 Giselle Evita Koch. Source-available for review, all rights
reserved. See [LICENSE](LICENSE).
