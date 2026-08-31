-- Grain: one row per calendar day and deal stage, based on deal creation date.
select
    created_at_utc::date as activity_date,
    deal_stage,
    count(*) as deal_count,
    coalesce(sum(amount), 0) as total_deal_value
from {{ ref('fct_deal') }}
group by 1, 2
