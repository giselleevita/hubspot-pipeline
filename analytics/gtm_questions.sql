-- Questions a commercial team actually asks, answered against the marts.
-- Run with: psql "$DATABASE_URL" -f analytics/gtm_questions.sql

-- 1. What is in the pipeline right now, by stage?
select
    deal_stage,
    count(*)                         as deals,
    sum(coalesce(amount, 0))         as pipeline_value,
    round(avg(amount), 0)            as avg_deal_value,
    count(*) filter (where amount is null) as deals_missing_amount
from analytics_marts.fct_deal
group by deal_stage
order by pipeline_value desc;

-- 2. How much pipeline was created each month?
select
    date_trunc('month', created_at_utc)::date as created_month,
    count(*)                                  as deals_created,
    sum(coalesce(amount, 0))                  as value_created
from analytics_marts.fct_deal
group by 1
order by 1 desc
limit 12;

-- 3. Which accounts carry the most open pipeline?
-- Joined through the bridge, so a deal shared by two companies is visible to
-- both rather than silently assigned to one of them.
select
    company.company_name,
    company.country,
    count(distinct deal.deal_id)     as open_deals,
    sum(coalesce(deal.amount, 0))    as open_value
from analytics_marts.fct_deal          as deal
join analytics_marts.bridge_deal_company as bridge on bridge.deal_id = deal.deal_id
join analytics_marts.dim_company       as company on company.company_id = bridge.company_id
where deal.deal_stage not in ('closedwon', 'closedlost')
group by company.company_name, company.country
order by open_value desc
limit 10;

-- 4. Which accounts have deals but nobody attached to them?
-- An onboarding handover with no named person is the practical version of a
-- data quality problem.
select
    company.company_name,
    count(distinct deal.deal_id) as deals
from analytics_marts.fct_deal            as deal
join analytics_marts.bridge_deal_company as bridge  on bridge.deal_id = deal.deal_id
join analytics_marts.dim_company         as company on company.company_id = bridge.company_id
left join analytics_marts.bridge_deal_contact as people on people.deal_id = deal.deal_id
where people.contact_id is null
group by company.company_name
order by deals desc
limit 10;

-- 5. How often is a deal shared between companies?
-- This is the number that decides whether the bridge table earns its place.
select
    company_count,
    count(*) as deals
from (
    select deal_id, count(distinct company_id) as company_count
    from analytics_marts.bridge_deal_company
    group by deal_id
) as per_deal
group by company_count
order by company_count;
