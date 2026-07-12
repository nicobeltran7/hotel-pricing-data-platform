-- The transformation showpiece: build a complete date spine per
-- property x duration band, blend vendors into a daily median, then
-- forward-fill observation gaps with window functions.
--
-- Vendors shop irregularly, so raw coverage has holes. Downstream BI
-- needs a dense daily series; is_gap_filled keeps the fill honest.

with bounds as (

    select min(rate_date) as start_date, max(rate_date) as end_date
    from {{ ref('stg_rate_observations') }}

),

spine as (

    -- dense calendar between first and last observation
    select cast(gs.d as date) as rate_date
    from bounds
    cross join generate_series(bounds.start_date, bounds.end_date, interval 1 day) as gs(d)

),

daily_median as (

    -- blend vendors: median is robust to a single vendor drifting
    select
        property_code,
        duration_band,
        rate_date,
        median(rate_usd)      as observed_rate,
        count(distinct vendor_code) as vendor_count
    from {{ ref('stg_rate_observations') }}
    group by 1, 2, 3

),

dense as (

    select
        pb.property_code,
        pb.duration_band,
        s.rate_date,
        dm.observed_rate,
        coalesce(dm.vendor_count, 0) as vendor_count
    from (select distinct property_code, duration_band from daily_median) as pb
    cross join spine s
    left join daily_median dm
        on  dm.property_code = pb.property_code
        and dm.duration_band = pb.duration_band
        and dm.rate_date     = s.rate_date

),

filled as (

    select
        *,
        last_value(observed_rate ignore nulls) over (
            partition by property_code, duration_band
            order by rate_date
            rows between unbounded preceding and current row
        ) as filled_rate,
        rate_date - max(case when observed_rate is not null then rate_date end) over (
            partition by property_code, duration_band
            order by rate_date
            rows between unbounded preceding and current row
        ) as days_since_observation
    from dense

)

select
    property_code,
    duration_band,
    rate_date,
    observed_rate,
    filled_rate,
    (observed_rate is null and filled_rate is not null) as is_gap_filled,
    coalesce(days_since_observation, 0)                 as days_since_observation,
    vendor_count
from filled
where filled_rate is not null  -- drop leading days before first observation
