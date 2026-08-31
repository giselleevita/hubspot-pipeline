-- Grain: one row per current HubSpot company. This is a Type 1 dimension.
select
    company_id,
    company_name,
    domain,
    industry,
    country,
    employee_count,
    created_at_utc,
    modified_at_utc
from {{ ref('stg_hubspot__companies') }}
