-- Grain: one row per current HubSpot company.
select company_id, company_name, domain, industry, created_at_utc, modified_at_utc
from {{ ref('stg_hubspot__companies') }}
