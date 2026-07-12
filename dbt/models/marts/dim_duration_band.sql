-- Static duration-band dimension with sort order for BI tools.

select * from (
    values
        ('1N',   '1 night',      1),
        ('2-3N', '2-3 nights',   2),
        ('4-6N', '4-6 nights',   3),
        ('7+N',  '7+ nights',    4)
) as t(duration_band, band_label, sort_order)
