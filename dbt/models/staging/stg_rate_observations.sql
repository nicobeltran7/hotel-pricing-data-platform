-- Typed, renamed pass over the raw landing table. One row per
-- vendor x property x rate_date x duration_band (enforced upstream by upsert PK).

select
    vendor_code,
    property_code,
    cast(rate_date as date)          as rate_date,
    duration_band,
    cast(rate_usd as decimal(9, 2))  as rate_usd,
    loaded_at
from {{ source('raw', 'rate_observations') }}
