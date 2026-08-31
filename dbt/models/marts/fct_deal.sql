-- Grain: one row per deal. Multi-valued CRM associations live in bridge tables.
select deal_id, deal_name, amount, deal_stage, created_at_utc, closed_at_utc, modified_at_utc
from {{ ref('stg_hubspot__deals') }}
