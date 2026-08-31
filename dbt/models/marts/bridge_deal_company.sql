-- Grain: one row per deal-company relationship; avoids a lossy single-company assumption.
select deal_id, company_id from {{ ref('stg_hubspot__deal_company') }}
