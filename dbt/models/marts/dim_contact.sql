-- Grain: one row per current HubSpot contact. This is a Type 1 dimension.
select contact_id, email, first_name, last_name, created_at_utc, modified_at_utc
from {{ ref('stg_hubspot__contacts') }}
