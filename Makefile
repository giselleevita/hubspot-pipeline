.PHONY: test demo run fixtures clean

test:
	.venv/bin/python -m pytest tests/ -q

# Build every model over generated data, no HubSpot token required.
demo: fixtures
	DBT_HOST=localhost .venv/bin/dbt build --project-dir dbt --profiles-dir dbt --target demo

fixtures:
	DATABASE_URL="postgresql://pipeline:pipeline@localhost:5432/hubspot" \
		.venv/bin/python -m scripts.load_fixture

# Extract from HubSpot, then build and test, against the real portal.
run:
	docker compose --profile run run --rm pipeline

clean:
	rm -rf dbt/target dbt/logs
