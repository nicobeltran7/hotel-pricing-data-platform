-- Singular test: a gap-filled row must have no same-day observation
-- (vendor_count = 0 and observed_rate null), and vice versa.

select *
from {{ ref('fct_daily_rates') }}
where (is_gap_filled and (vendor_count > 0 or observed_rate is not null))
   or (not is_gap_filled and observed_rate is null)
