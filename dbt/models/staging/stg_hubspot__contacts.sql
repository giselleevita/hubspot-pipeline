select
    object_id as contact_id,
    nullif(payload->'properties'->>'email', '') as email,
    nullif(payload->'properties'->>'firstname', '') as first_name,
    nullif(payload->'properties'->>'lastname', '') as last_name,
    nullif(payload->'properties'->>'createdate', '')::timestamptz at time zone 'UTC' as created_at_utc,
    nullif(payload->'properties'->>'hs_lastmodifieddate', '')::timestamptz at time zone 'UTC' as modified_at_utc,
    ingested_at
from {{ source('hubspot_raw', 'contacts') }}
