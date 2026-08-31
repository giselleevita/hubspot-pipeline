# HubSpot → PostgreSQL pipeline

This project incrementally extracts HubSpot contacts, companies, deals, and their many-to-many associations into PostgreSQL, then uses dbt to produce typed staging views and query-ready GTM marts. It is a small but production-shaped example of the system behind questions such as “which institutions have active opportunities, who is involved, and how much pipeline was created by stage?”

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

The fact table grain is one row per HubSpot deal because a deal is the unit whose value and stage the commercial team measures. Associations are separate bridge tables because forcing multiple contacts or companies into one foreign key silently loses information. Contact and company are current-state (Type 1) dimensions: changed emails or names overwrite the prior value. If historical attributes mattered—for example, attributing pipeline to the company segment at the time of creation—I would add effective dates and current-row flags as Type 2 dimensions.

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

Run unit tests locally with `python -m pytest -q`: 17 tests covering pagination, the per-object modification property, re-anchoring at the search cap, retry and backoff, the lookback window, and the association delete-before-insert rule. None of them need a network or a database. `dbt test` adds 22 tests over the built models. Inspect `pipeline_runs` for start and end time, status, extracted row counts, and errors. A run that loads nothing prints a warning and, with `FAIL_ON_EMPTY_RUN=true`, exits non-zero.

To seed an authorized HubSpot test portal with deterministic demo companies, contacts, deals, and associations, temporarily add the three CRM `write` scopes and run `docker compose --profile run run --rm --entrypoint python pipeline -m scripts.seed_demo`. Remove the write scopes afterwards; the pipeline itself only needs read access.

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
