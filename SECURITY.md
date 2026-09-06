# Security

This is a portfolio project, not a supported product. It is still built to be safe
to run and to review.

## Reporting a vulnerability

Email **giselle.evita@gmail.com**. Please do not open a public issue for anything
that looks exploitable. Expect an acknowledgement within a few days.

## Handling of credentials

- The only secret this project needs is a HubSpot **private-app token**, read from
  `.env` (git-ignored). It is never logged and never written to the database.
- The extractor requires **read** scopes only
  (`crm.objects.{contacts,companies,deals}.read`, `crm.schemas.*.read`).
  `scripts/seed_demo.py` is the one script that needs write scopes; the intended
  flow is to add them, seed, then remove them again — see
  [docs/DESIGN.md](docs/DESIGN.md).
- `scripts/load_fixture.py` needs no token at all and writes only to a separate
  `hubspot_demo` database, so a reviewer never has to supply real credentials.

## Data handling

- Raw API responses are stored as-is in a local PostgreSQL instance for replayability.
  They are not transmitted anywhere else.
- There is no telemetry and no outbound network traffic other than calls to the
  HubSpot API you configure.

## Dependencies

Python dependencies are pinned in `requirements.txt`; Dependabot updates are enabled
on the repository.
