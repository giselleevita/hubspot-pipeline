-- Grain: one row per contact-company relationship.
select contact_id, company_id from {{ ref('stg_hubspot__contact_company') }}
