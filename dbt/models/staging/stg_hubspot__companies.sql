select
    object_id as company_id,
    nullif(payload->'properties'->>'name', '') as company_name,
    nullif(payload->'properties'->>'domain', '') as domain,
    nullif(payload->'properties'->>'industry', '') as industry,
    nullif(payload->'properties'->>'createdate', '')::timestamptz at time zone 'UTC' as created_at_utc,
    nullif(payload->'properties'->>'hs_lastmodifieddate', '')::timestamptz at time zone 'UTC' as modified_at_utc,
    ingested_at
from {{ source('hubspot_raw', 'companies') }}
