-- Grain: one row per deal-contact relationship; a deal can involve many people.
select deal_id, contact_id from {{ ref('stg_hubspot__deal_contact') }}
