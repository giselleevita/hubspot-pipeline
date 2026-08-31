select
    object_id as deal_id,
    nullif(payload->'properties'->>'dealname', '') as deal_name,
    nullif(payload->'properties'->>'amount', '')::numeric(18, 2) as amount,
    nullif(payload->'properties'->>'dealstage', '') as deal_stage,
    nullif(payload->'properties'->>'createdate', '')::timestamptz at time zone 'UTC' as created_at_utc,
    nullif(payload->'properties'->>'closedate', '')::timestamptz at time zone 'UTC' as closed_at_utc,
    nullif(payload->'properties'->>'hs_lastmodifieddate', '')::timestamptz at time zone 'UTC' as modified_at_utc,
    ingested_at
from {{ source('hubspot_raw', 'deals') }}
