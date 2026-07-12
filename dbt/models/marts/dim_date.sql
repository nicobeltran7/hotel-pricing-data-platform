-- Calendar dimension with integer surrogate key (yyyymmdd).

with bounds as (

    select min(rate_date) as start_date, max(rate_date) as end_date
    from {{ ref('stg_rate_observations') }}

),

days as (

    select cast(gs.d as date) as date_actual
    from bounds
    cross join generate_series(bounds.start_date, bounds.end_date, interval 1 day) as gs(d)

)

select
    cast(strftime(date_actual, '%Y%m%d') as integer) as date_key,
    date_actual,
    year(date_actual)                                as year,
    quarter(date_actual)                             as quarter,
    month(date_actual)                               as month,
    strftime(date_actual, '%B')                      as month_name,
    dayofweek(date_actual)                           as day_of_week,
    strftime(date_actual, '%A')                      as day_name,
    dayofweek(date_actual) in (0, 6)                 as is_weekend,
    cast(strftime(date_actual, '%Y%m') as integer)   as year_month_key
from days
