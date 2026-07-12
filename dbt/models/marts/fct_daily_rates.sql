-- Daily rate fact, one row per property x duration band x date.
-- Incremental: only (re)processes dates on/after the max already loaded,
-- so late corrections within the window are picked up on the next run.

{{
    config(
        materialized='incremental',
        unique_key=['date_key', 'property_code', 'duration_band'],
        incremental_strategy='delete+insert'
    )
}}

select
    cast(strftime(f.rate_date, '%Y%m%d') as integer) as date_key,
    f.property_code,
    f.duration_band,
    f.observed_rate,
    f.filled_rate,
    f.is_gap_filled,
    f.days_since_observation,
    f.vendor_count
from {{ ref('int_daily_rates_filled') }} as f

{% if is_incremental() %}
where f.rate_date >= (
    select coalesce(max(cast(strptime(cast(date_key as varchar), '%Y%m%d') as date)), date '1900-01-01') - interval 7 day
    from {{ this }}
)
{% endif %}
