-- Property dimension from the reference seed, with market attributes denormalized.

select
    property_code,
    property_name,
    market_code,
    market_name,
    rooms,
    case
        when rooms >= 300 then 'Large'
        when rooms >= 150 then 'Mid'
        else 'Small'
    end as size_tier
from {{ ref('properties') }}
