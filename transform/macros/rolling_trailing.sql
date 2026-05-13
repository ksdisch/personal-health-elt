{#
    rolling_trailing — returns an OVER clause for a trailing N-day window.

    Two flavors, controlled by `inclusive`:

      inclusive=true (default)   rows between (window_days - 1) preceding and current row
      inclusive=false            rows between window_days preceding and 1 preceding

    Inclusive is the "today + last N-1" trailing window used for rolling
    averages where today should be part of its own average (e.g.,
    `mart_training_load.acute_load_7d`).

    Exclusive is the "strictly prior N days" window used for z-score
    baselines where today should NOT be included in its own threshold
    (e.g., `mart_daily_anomaly_bands` rolling mean / std).

    Arguments
    ---------
    window_days : int
        Number of days in the window.
    partition_by : str | none
        Optional `partition by ...` column expression. None = single
        time series (no partition).
    order_by : str = 'day'
        Column to order the window by. Defaults to `day` which matches
        every consumer in this project today.
    inclusive : bool = true
        See above.

    Usage
    -----
        sum(zone_2_min) {{ rolling_trailing(7) }} as zone_2_min_7d,

        avg(value) {{ rolling_trailing(28,
                        partition_by='metric',
                        inclusive=false) }} as rolling_mean,
#}
{% macro rolling_trailing(window_days, partition_by=none, order_by='day', inclusive=true) -%}
    over (
        {%- if partition_by %} partition by {{ partition_by }}{% endif %}
        order by {{ order_by }}
        rows between
        {%- if inclusive %} {{ window_days - 1 }} preceding and current row
        {%- else %} {{ window_days }} preceding and 1 preceding
        {%- endif %}
    )
{%- endmacro %}
