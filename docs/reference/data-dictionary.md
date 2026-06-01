# Data Dictionary — `personal-health-elt`

> **Status:** Canonical. This repo is the single source of truth for the
> `mart_recovery_state` contract across all **three** consumers (the
> `weekly-health-review` Claude skill, the Tempo PWA Firestore feed, and the
> `daily-workout-coach` Claude skill). The Tempo PWA repo
> ([`ksdisch/stopwatch`](https://github.com/ksdisch/stopwatch)) links back here.
>
> **Contract version:** `v0.3.x` (pre-release). No git tags exist yet; semantic
> tags + a `CHANGELOG.md` are being backfilled from PR history (#1–#30). The
> `mart_recovery_state` contract has been stable since the daily-workout-coach
> consumer landed (PR #27) and the Tempo Firestore feed (PR #31 / current branch).
>
> **Last verified:** 2026-05-31 against dbt-core 1.11.8 and the live warehouse
> (`dbt build --select mart_recovery_state` → 6/6 pass; the `with_hrv_trend` CTE
> compiles and executes — the artifacts-plan "missing comma" flag was a false
> positive).

This dictionary documents the analytics layer that downstream consumers read:
the **public-API mart** and its Firestore projection, then a full catalog of all
**17 marts**, the **7 raw tables**, the supporting staging/intermediate models,
the seeds, and a domain **glossary**.

All `date` columns and `timestamp` columns are **`America/Chicago` local**
(timezone is normalized once, at the staging layer; see [ADR planned] /
`CLAUDE.md`). `timestamp` columns are `timestamp without time zone` holding local
wall-clock time.

---

## Table of contents

1. [The public API — `mart_recovery_state`](#1-the-public-api--mart_recovery_state)
2. [The Firestore contract — `users/{uid}/recovery_state`](#2-the-firestore-contract--usersuidrecovery_state)
3. [The three consumers & the lockstep rule](#3-the-three-consumers--the-lockstep-rule)
4. [Mart catalog (all 17)](#4-mart-catalog-all-17)
5. [Raw tables (7)](#5-raw-tables-7)
6. [Supporting models & seeds](#6-supporting-models--seeds)
7. [Glossary](#7-glossary)

---

## 1. The public API — `mart_recovery_state`

| | |
|---|---|
| **Relation** | `analytics_marts.mart_recovery_state` |
| **Grain** | One row per **calendar day** (`America/Chicago`). |
| **Materialization** | `table` (default for marts). |
| **Built from** | `mart_daily_rhr` ⨝ `mart_daily_hrv` ⨝ `mart_training_load` (full outer join on `day`). |
| **Contract tests** (`transform/models/marts/schema.yml`) | `not_null(day)`, `unique(day)`, `not_null(is_today)`, `not_null(recovery_signal)`, `accepted_values(recovery_signal)`. These dbt tests are the durable, machine-enforced contract surface. |

### Columns

| # | Column | Type | Null? | Description |
|---|---|---|---|---|
| 1 | `day` | `date` | no | Calendar date, `America/Chicago`. Primary key (`unique` + `not_null`). |
| 2 | `is_today` | `boolean` | no | `day = current_date` at build time. Lets a consumer pick "today's" row without re-deriving it. |
| 3 | `rhr_bpm` | `double precision` | yes | Resting heart rate (bpm), from `mart_daily_rhr`. |
| 4 | `hrv_ms` | `double precision` | yes | Heart-rate variability (SDNN, ms), from `mart_daily_hrv`. |
| 5 | `hrv_ms_7d_prior_avg` | `double precision` | yes | Trailing HRV baseline: `avg(hrv_ms)` over the window `rows between 7 preceding and 1 preceding` (excludes the current day). Rounded to 1 dp. The denominator for the HRV-drop rule. |
| 6 | `zone_2_min_today` | `double precision` | yes | Minutes in HR Zone 2 on `day` (from `mart_training_load.zone_2_min`). |
| 7 | `zone_2_min_7d` | `double precision` | yes | Rolling 7-day Zone-2 minutes. |
| 8 | `strength_sessions_7d` | `numeric` | yes | Count of strength sessions in the trailing 7 days. |
| 9 | `training_load_today` | `double precision` | yes | Day's training load (Banister-style TRIMP; `mart_training_load.training_load`). |
| 10 | `acute_load_7d` | `double precision` | yes | Rolling 7-day acute load. |
| 11 | `chronic_load_28d` | `double precision` | yes | Rolling 28-day chronic load. |
| 12 | `acwr` | `double precision` | yes | Acute-to-chronic workload ratio = `acute_load_7d / chronic_load_28d`. Sweet spot 0.8–1.3; injury-risk > 1.5. |
| 13 | `days_since_last_workout` | `integer` | yes | Distance in days back to the most recent day with `training_load_today > 0`. |
| 14 | `recovery_signal` | `text` | yes (enum) | Rule-based recovery bucket. See enum below. |

> The downstream consumers may reason about the raw inputs directly —
> `recovery_signal` is a **convenience bucket, not a gate**.

### `recovery_signal` enum + rule logic

`recovery_signal ∈ { well_recovered, neutral, strained, insufficient_data }`
(enforced by the dbt `accepted_values` test). Rules are evaluated top-down in
`mart_recovery_state.sql`:

| Order | Bucket | Condition |
|---|---|---|
| 1 | `insufficient_data` | `hrv_ms IS NULL` **or** `hrv_ms_7d_prior_avg IS NULL` **or** `acwr IS NULL` |
| 2 | `strained` | `acwr > 1.5` (acute spike) |
| 3 | `strained` | `hrv_ms < hrv_ms_7d_prior_avg * 0.85` (HRV ≥15% below baseline) |
| 4 | `well_recovered` | `acwr BETWEEN 0.8 AND 1.3` **and** `hrv_ms >= hrv_ms_7d_prior_avg * 0.95` |
| 5 | `neutral` | everything else |

### Change rule (read before editing the mart)

`mart_recovery_state.sql` is **contract-protected** (`CLAUDE.md`). Renaming a
column, dropping a field, or changing a unit requires updating, **in the same
change**:

- this data dictionary (§1 and §2),
- `scripts/push_recovery_state.py` (Firestore feed),
- `scripts/weekly_health_review.py` (weekly briefing),
- `scripts/daily_workout_coach.py` (daily card),
- the dbt tests in `transform/models/marts/schema.yml`.

The `accepted_values(recovery_signal)` + `unique(day)` tests fail **before** any
consumer does — that is the intended early-warning.

---

## 2. The Firestore contract — `users/{uid}/recovery_state`

A **one-way** feed (server writes, client reads), written by
`scripts/push_recovery_state.py` — invoked as the last step of the `weekly_load`
Prefect flow, and runnable standalone:

```bash
uv run python scripts/push_recovery_state.py [--days N] [--dry-run]
```

It fetches the trailing **`--days` (default 14)** rows of `mart_recovery_state`
(`WHERE day > current_date - :days`, ordered by `day`) and writes **two
documents**:

```
users/{uid}/recovery_state/latest     # the most recent day's row
users/{uid}/recovery_state/history    # { rows: [trailing window], updated_at }
```

The Tempo PWA ([`ksdisch/stopwatch`](https://github.com/ksdisch/stopwatch)) reads
these via `SyncFirestore.getDoc` and renders a readiness band above its Rhythm
timeline. **No-op** when `TEMPO_FIREBASE_SA_PATH` / `TEMPO_FIREBASE_USER_UID`
are unset (so a portfolio clone never breaks).

### `latest` document

Carries **all 14 mart columns** of the most recent row, plus `updated_at`. Each
cell is JSON-safed for the Firestore SDK (`_json_safe` in
`push_recovery_state.py`):

| Field | Firestore type | Source / coercion |
|---|---|---|
| `day` | string (`YYYY-MM-DD`) | `date` → ISO string |
| `is_today` | boolean | passthrough |
| `recovery_signal` | string | passthrough (enum, see §1) |
| `rhr_bpm` | number / null | `double precision` → float; `NaN` → `null` |
| `hrv_ms` | number / null | float / null |
| `hrv_ms_7d_prior_avg` | number / null | float / null |
| `zone_2_min_today` | number / null | float / null |
| `zone_2_min_7d` | number / null | float / null |
| `strength_sessions_7d` | number / null | `numeric` → `Decimal` → float |
| `training_load_today` | number / null | float / null |
| `acute_load_7d` | number / null | float / null |
| `chronic_load_28d` | number / null | float / null |
| `acwr` | number / null | float / null |
| `days_since_last_workout` | integer / null | `integer` passthrough |
| `updated_at` | string (ISO 8601, `…Z`) | UTC push timestamp (added by the feed, not a mart column) |

### `history` document

```jsonc
{
  "rows": [ { /* one serialized row per day, oldest → newest, same 14 fields as `latest` (minus updated_at) */ } ],
  "updated_at": "2026-05-31T11:00:00.000000Z"
}
```

`rows` is ordered oldest-first and holds the trailing window (default 14 days).
On an empty mart, `latest` is not written and `history` is `{ "rows": [],
"updated_at": … }`.

> **Coercion contract:** `NaN`/`NaT`/`None` → `null`; `date`/`Timestamp` → ISO
> `YYYY-MM-DD`; `Decimal`/NumPy scalars → Python `float`/`int`; `bool` stays
> `bool`. Adding a column to `mart_recovery_state` automatically propagates it
> into both documents (the feed serializes whatever columns the query returns) —
> which is exactly why a schema change here is a **contract change** for Tempo.

---

## 3. The three consumers & the lockstep rule

| # | Consumer | Kind | Reads | Produces | Code |
|---|---|---|---|---|---|
| 1 | **weekly-health-review** | Claude skill | `mart_recovery_state` (+ daily marts), last 7 days | An H2 Markdown block (signal headline, day-by-day table, 1–4 rule-based recommendations) → vault `40-areas/health/weekly-health-reviews.md` | `scripts/weekly_health_review.py` · exposure `weekly_health_review` · repo [`ksdisch/weekly-health-review`](https://github.com/ksdisch/weekly-health-review) |
| 2 | **Tempo PWA (Firestore feed)** | Firestore feed | `mart_recovery_state`, trailing 14 days (all 14 cols) | `latest` + `history` docs under `users/{uid}/recovery_state` | `scripts/push_recovery_state.py` · repo [`ksdisch/stopwatch`](https://github.com/ksdisch/stopwatch) |
| 3 | **daily-workout-coach** | Claude skill | latest `mart_recovery_state` row + trailing 14d `mart_training_load` | A daily H2 card (session type, target zone, target minutes, rationale) → vault `40-areas/health/daily-workout-coach.md` | `scripts/daily_workout_coach.py` · exposure `daily_workout_coach` · skill `~/Cowork/skills/daily-workout-coach/` |

The coach's decision table keys on `recovery_signal × acwr × days_since_last_workout ×
Zone-2 deficit × strength deficit`, against targets of **180 min Zone 2 / week**
and **2 strength sessions / week**, ACWR sweet spot **0.8–1.3** (>1.5 = red, <0.8 =
safe to add volume). A change to the `recovery_signal` vocabulary or any consumed
column ripples into all three scripts above — update them in lockstep.

> dbt also declares a fourth exposure, `forecast_page` (the `11_forecast`
> Streamlit page), which depends on the forecast marts, **not** on
> `mart_recovery_state`. It is therefore not a recovery-state contract consumer.

---

## 4. Mart catalog (all 17)

`analytics_marts.*` — all materialized as `table`. One public-API mart
(`mart_recovery_state`, §1) plus 16 others, grouped below. Timestamps are
`America/Chicago` local.

### Daily physiology

#### `mart_daily_rhr` — daily resting heart rate
Grain: one row per day (primary-source-only via staging dedup).

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `resting_heart_rate` | `double precision` | RHR (bpm). |
| `source_name` | `text` | Winning device for the day. |
| `unit` | `text` | Unit string (`count/min`). |

#### `mart_daily_hrv` — daily HRV (SDNN)
Grain: one row per day. Apple Watch takes multiple HRV samples during sleep; averaged here.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `hrv_ms` | `double precision` | HRV (SDNN, ms). |
| `sample_count` | `bigint` | HRV samples averaged for the day. |
| `unit` | `text` | Unit string (`ms`). |

#### `mart_daily_vo2max` — daily VO₂ max
Grain: one row per day. Sparse — Apple emits a reading only after outdoor workouts.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `vo2max` | `double precision` | VO₂ max (mL/(kg·min)). |
| `sample_count` | `bigint` | Readings averaged for the day. |
| `unit` | `text` | Unit string. |

#### `mart_daily_weight` — daily body mass
Grain: one row per day (last reading wins). Currently empty — no smart scale tracked.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `weight_kg` | `double precision` | Body mass (kg). |
| `source_name` | `text` | Source device/app. |
| `unit` | `text` | Unit string. |

### Derived daily

#### `mart_daily_signals` — wide daily signals for correlation
Grain: one row per day. Thin selector on `mart_recovery_state` with a numeric
`recovery_score`. Internal correlation lens (companion to the public-API mart).

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `rhr_bpm` | `double precision` | RHR for the day. |
| `hrv_ms` | `double precision` | HRV (SDNN, ms). |
| `trimp` | `double precision` | Day's TRIMP-style load (aliased from `training_load_today`). |
| `acwr` | `double precision` | Acute-to-chronic workload ratio. |
| `recovery_signal` | `text` | Rule-based bucket (same enum as §1). |
| `recovery_score` | `integer` | Numeric encoding: `well_recovered→1`, `neutral→0`, `strained→-1`, `insufficient_data→null`. |
| `sleep_minutes` | `double precision` | Nightly sleep minutes (joined from the sleep stack). |

#### `mart_daily_anomaly_bands` — z-scored daily metrics
Grain: one row per `(metric, day)`. Rolling 28-day mean/std computed strictly
before today (`28 preceding … 1 preceding`) so a fresh anomaly doesn't dilute its
own threshold. `|z| > 2` flags an anomaly on page `06_anomaly`.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date. |
| `metric` | `text` | One of `rhr_bpm`, `hrv_ms`, `sleep_min`. |
| `value` | `double precision` | Raw metric value. |
| `rolling_mean` | `double precision` | Trailing 28-day mean (excludes today). Null during warm-up. |
| `rolling_std` | `double precision` | Trailing 28-day sample stddev. Null during warm-up / zero variance. |
| `z_score` | `double precision` | `(value - rolling_mean) / rolling_std`. Null when std is null/zero. |

#### `mart_daily_context` — external-context join
Grain: one row per day. Weather + calendar density for correlation on page `09`.
Kept separate so the public API stays focused on internal signals.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `temp_min_c` / `temp_max_c` | `double precision` | Daily min/max temperature (°C). |
| `temp_afternoon_c` / `temp_night_c` | `double precision` | Afternoon / overnight temperature (°C). |
| `humidity_afternoon` | `double precision` | Mid-afternoon relative humidity (%). |
| `cloud_cover_afternoon` | `double precision` | Mid-afternoon cloud cover (%). |
| `precip_total_mm` | `double precision` | Total daily precipitation (mm). |
| `wind_max_mps` | `double precision` | Peak wind speed (m/s). |
| `timed_event_count` | `integer` | Non-all-day calendar events; 0 when calendar unconfigured. |
| `timed_event_hours` | `double precision` | Sum of timed-event durations (hours). |
| `all_day_event_count` | `integer` | All-day events covering the day. |
| `first_event_local` / `last_event_local` | `timestamp` | First/last timed-event bounds (local); null when none. |

### Training

#### `mart_training_load` — daily load + rolling windows
Grain: one row per day (date-spine filled so zero-load days denominate). `acwr =
acute_load_7d / chronic_load_28d`.

| Column | Type | Description |
|---|---|---|
| `day` | `date` | Calendar date (`unique`). |
| `zone_2_min` | `double precision` | Minutes in Zone 2 for the day. |
| `zone_2_min_7d` | `double precision` | Rolling 7-day Zone-2 minutes. |
| `strength_sessions_7d` | `numeric` | Rolling 7-day strength session count. |
| `strength_min_7d` | `double precision` | Rolling 7-day strength minutes. |
| `training_load` | `double precision` | Banister-style TRIMP (Z1–Z5 minutes weighted 1..5). |
| `acute_load_7d` | `double precision` | Rolling 7-day acute load. |
| `chronic_load_28d` | `double precision` | Rolling 28-day chronic load. |
| `acwr` | `double precision` | Acute-to-chronic workload ratio. |

#### `mart_workout_zones` — per-workout HR zone breakdown
Grain: one row per workout. Time-in-zone from the `hr_zones` seed + the range-join.

| Column | Type | Description |
|---|---|---|
| `day_local` | `date` | Workout date (local). |
| `activity_type` | `text` | Activity (Running, Cycling, …). |
| `start_ts_local` | `timestamp` | Workout start (local). |
| `duration_sec` | `double precision` | Workout duration (s). |
| `zone_1_sec` … `zone_5_sec` | `double precision` | Seconds in each of the 5 HR zones. |
| `hr_sample_count` | `bigint` | HR samples in the workout. |
| `avg_hr_bpm` / `max_hr_bpm` | `double precision` | Average / max HR (bpm). |

#### `mart_workout_hrr` — per-workout heart-rate recovery
Grain: one row per workout. Each `hrr_*s` is tolerance-gated (±15s, or ±30s at
120s) — NULL rather than mislabel a far sample. The leading aerobic-capacity
signal (shifts months before RHR).

| Column | Type | Description |
|---|---|---|
| `activity_type` | `text` | Workout activity. |
| `day_local` | `date` | Workout date (local). |
| `workout_start_local` / `workout_end_local` | `timestamp` | Workout bounds (local). |
| `peak_hr_bpm` | `integer` | Max HR inside the workout window. |
| `hr_at_30s` / `hr_at_60s` / `hr_at_120s` | `integer` | Post-workout HR nearest each target offset. NULL outside tolerance. |
| `offset_at_30s` / `offset_at_60s` / `offset_at_120s` | `double precision` | Actual seconds-after-end of the chosen sample. |
| `hrr_30s` / `hrr_60s` / `hrr_120s` | `integer` | `peak_hr_bpm − hr_at_Ns`. `hrr_60s` is the headline (25–35 typical, 40+ excellent, <15 poor). |

#### `mart_monthly_aerobic_efficiency` — monthly Zone-2 efficiency
Grain: one row per calendar month. The slow-moving fitness signal: time-weighted
avg Z2 HR drifts down as the aerobic base builds.

| Column | Type | Description |
|---|---|---|
| `month` | `date` | First day of the month (`unique`). |
| `avg_z2_hr` | `double precision` | Time-weighted avg HR across Zone-2 samples: `Σ(hr·dur)/Σ(dur)`. |
| `z2_minutes` | `double precision` | Total Zone-2 minutes in the month. |
| `sample_count` | `bigint` | Zone-2 HR samples aggregated (low = noisy). |

### Sleep

#### `mart_sleep_nights` — per-night rollup + composite score
Grain: one row per `night_date` (main sleep period only; naps excluded). Score
weights live in the `sleep_score_weights` seed.

| Column | Type | Description |
|---|---|---|
| `night_date` | `date` | Date you woke up (`unique`). |
| `time_in_bed_min` | `double precision` | Minutes in bed. |
| `time_asleep_min` | `double precision` | Minutes asleep (Core+Deep+REM+Unspecified+legacy). |
| `sleep_efficiency_pct` | `double precision` | `100 · asleep / in_bed`. |
| `rem_min` / `deep_min` / `core_min` / `awake_min` | `double precision` | Minutes per stage. |
| `rem_pct_of_sleep` / `deep_pct_of_sleep` | `double precision` | Stage % of time asleep. |
| `awakening_count` | `bigint` | Contiguous awake spans. |
| `bedtime_local` / `wake_time_local` | `timestamp` | Night bounds (local). |
| `composite_score` | `double precision` | Sleep score in [0,100]: weighted efficiency + REM% + deep% vs. targets, minus a per-awakening fragmentation penalty. |

#### `mart_sleep_naps` — per-nap rollup
Grain: one row per non-main sleep period containing actual sleep. Sibling to
`mart_sleep_nights`.

| Column | Type | Description |
|---|---|---|
| `nap_date` | `date` | Calendar date the nap started (local). |
| `night_date` | `date` | Upstream noon-to-noon night attribution. |
| `period_seq` | `bigint` | 1-indexed period id within the night. |
| `nap_start_local` / `nap_end_local` | `timestamp` | Nap bounds (local; start is `unique`). |
| `duration_min` | `double precision` | Wall-clock span (min). |
| `time_asleep_min` | `double precision` | Minutes asleep within the nap (>0 by definition). |
| `awakening_count` | `bigint` | Awake segments within the nap. |

#### `mart_sleep_stages` — hypnogram segments
Grain: one row per sleep-stage segment per night, with an in-night sequence index.

| Column | Type | Description |
|---|---|---|
| `night_date` | `date` | Date you woke up (noon-to-noon attribution). |
| `stage_start_local` / `stage_end_local` | `timestamp` | Segment bounds (local). |
| `duration_min` | `double precision` | Segment duration (min). |
| `sleep_stage` | `text` | Apple label ∈ `{asleepCore, asleepDeep, asleepREM, asleepUnspecified, asleep, awake, inBed}`. |
| `is_asleep` | `boolean` | True for the five `asleep*` values. |
| `source_name` | `text` | Recording device. |
| `stage_seq_in_night` | `bigint` | 1-based ordinal within the night, ordered by start. |

### Forecasting

#### `mart_forecast_bands` — Holt forecasts + confidence bands
Grain: one row per `(metric, day)` over history **and** the next 7 days. Three
metrics get fitted Holt forecasts (`rhr_bpm`, `hrv_ms`, `training_load`; α=0.3,
β=0.1 via the `holt_forecast` macro); `acwr` is a deterministic projection from
forecasted `training_load` (no fitted band). See `docs/design/forecasting-marts.md`
(planned).

| Column | Type | Description |
|---|---|---|
| `metric` | `text` | ∈ `{rhr_bpm, hrv_ms, training_load, acwr}`. |
| `day` | `date` | Historical OR future forecast day. |
| `value` | `double precision` | Actual on historical rows; NULL on forecast rows. |
| `smoothed` | `double precision` | Holt level (in-sample fit); NULL on forecast + all ACWR rows. |
| `forecast` | `double precision` | NULL on history; `level_T + h·trend_T` on forecast rows (deterministic projection for ACWR). |
| `forecast_lower` / `forecast_upper` | `double precision` | `forecast ∓ 1.96·σ·√h`. NULL on history + ACWR rows. |
| `is_forecast` | `boolean` | False = historical, true = forecast horizon. |
| `horizon_day_offset` | `integer` | Days from the last historical day (1..7), NULL on history. |

#### `mart_forecast_backtest` — walk-forward backtest
Grain: one row per `(metric, cutoff_day, horizon h ∈ 1..7)`. Predicted-vs-realized
for the three fitted metrics; the page derives MAE/RMSE/MAPE. ACWR omitted
(its error is already captured via `training_load`).

| Column | Type | Description |
|---|---|---|
| `metric` | `text` | ∈ `{rhr_bpm, hrv_ms, training_load}`. |
| `cutoff_day` | `date` | Day whose level+trend produced the forecast. |
| `target_day` | `date` | `cutoff_day + horizon_days`. |
| `horizon_days` | `integer` | 1..7. |
| `forecast` | `double precision` | `level_cutoff + h·trend_cutoff`. |
| `actual` | `double precision` | Realized value at `target_day`. |
| `abs_error` | `double precision` | `abs(actual − forecast)` (≥ 0). |

---

## 5. Raw tables (7)

Schema `raw.*` — the landing zone. Loaders own these; dbt only reads 5 of them as
**sources**. Full PK/FK/index detail lives in
[`docs/diagrams/raw-erd.dbml`](../diagrams/raw-erd.dbml); freshness SLAs in
`transform/models/sources.yml` (warn > 2d, error > 7d on the HK tables).

| Table | dbt source? | Natural key (PK) | FK | Purpose |
|---|---|---|---|---|
| `raw.file_inventory` | no | `sha256` | — (hub) | SHA256 ledger; loaders skip any file whose hash is present. |
| `raw.quantities` | ✅ | `(metric_type, source_name, start_ts)` | `source_sha256 → file_inventory` | HK quantity samples (HR, HRV, RHR, VO₂, weight, energy, steps, …). |
| `raw.workouts` | ✅ | `(activity_type, source_name, start_ts)` | `source_sha256 → file_inventory` | HK workouts; one row per session. |
| `raw.categories` | ✅ | `(category_type, source_name, start_ts)` | `source_sha256 → file_inventory` | HK category samples (sleep stages, mindful, stand, HR-event). |
| `raw.weather` | ✅ | `(obs_date, lat, lon)` | — | OpenWeather daily summaries (API "standard" units). Optional. |
| `raw.calendar_daily` | ✅ | `(day, source_sha256)` | `source_sha256 → file_inventory` | Per-day Google Calendar density. Optional. |
| `raw.notification_log` | no | `(rule_name, day)` | — | Notification dedup ledger (once-per-(rule, day)). |

The four FK spokes (`quantities`, `workouts`, `categories`, `calendar_daily`) →
`file_inventory` are the **two-level idempotency** story: a file's hash and its
rows commit in one transaction, so a re-run of a seen file is a clean no-op.

---

## 6. Supporting models & seeds

**Staging (`analytics_staging.*`, views)** — TZ normalization + dedup happen
here, once.

| Model | Purpose |
|---|---|
| `stg_quantities` | Typed, UTC→`America/Chicago`, multi-source dedup (Apple Watch > iPhone > 3rd-party via `row_number()`, rank 1). |
| `stg_workouts` | Typed, TZ-normalized workouts. |
| `stg_categories` | Typed, TZ-normalized category samples (feeds the sleep stack). |
| `stg_weather` | Units converted from API "standard" (K, m/s) to °C etc. |
| `stg_calendar` | Latest-SHA-per-day calendar density. |

**Intermediate (`analytics_intermediate.*`)**

| Model | Materialization | Purpose |
|---|---|---|
| `int_workout_hr_samples` | `table` | Range-join workouts × HR samples; zone tag via `hr_zones`; `LEAD()` per-sample duration. The project's biggest cost — materialized so every downstream mart re-reads cheaply. |
| `int_sleep_segments` | view | Typed sleep-stage segments with noon-to-noon night attribution. |
| `int_sleep_periods` | view | Groups segments into periods (main night vs. naps, gap > 2h). |

**Seeds (`analytics_seeds.*`)** — configuration, not code.

| Seed | Purpose |
|---|---|
| `hr_zones` | HR zone boundaries. **Zone 2 locked at 136–153 bpm** (user's measured Z2). Always `ref('hr_zones')`; never hardcode in SQL. |
| `sleep_score_weights` | Composite-sleep-score weights + targets (efficiency / REM / deep / fragmentation). |

**Macros** — `holt_forecast` (Holt's linear smoothing, `WITH RECURSIVE`, α=0.3
β=0.1 horizon=7) and `rolling_trailing` (rolling-window helper).

---

## 7. Glossary

| Term | Meaning |
|---|---|
| **ELT** | Extract-Load-Transform: land raw data first (`raw.*`), transform in-warehouse with dbt. |
| **Mart** | A consumer-facing, query-optimized table (`analytics_marts.*`). Here, denormalized daily/per-event snapshots — not a star schema. |
| **Grain** | What exactly one row represents (e.g. one day, one workout, one sleep segment). |
| **RHR** | Resting heart rate (bpm). |
| **HRV (SDNN)** | Heart-rate variability, standard deviation of normal-to-normal intervals (ms). Apple Watch samples it during sleep. Higher trend = better recovery. |
| **VO₂ max** | Maximal oxygen uptake (mL/(kg·min)); Apple estimates it after outdoor workouts. |
| **HRR** | Heart-rate recovery: bpm drop at 30/60/120s after a workout. Leading aerobic-fitness signal. |
| **Zone 2 / HR zones** | Five HR intensity bands from `hr_zones.csv`. Zone 2 (136–153 bpm) is the aerobic-base zone. |
| **TRIMP (Banister)** | Training Impulse: zone minutes weighted 1..5, summed into a single daily load. |
| **Acute / chronic load** | Rolling 7-day (acute) vs 28-day (chronic) average load. |
| **ACWR** | Acute-to-chronic workload ratio = acute / chronic. Sweet spot **0.8–1.3**; injury-risk **> 1.5**; under-training **< 0.8**. |
| **`recovery_signal`** | Rule-based daily bucket ∈ `{well_recovered, neutral, strained, insufficient_data}` (see §1). A hint, not a gate. |
| **Aerobic efficiency** | Time-weighted average HR within Zone 2; drifts down as fitness improves at a fixed effort. |
| **Hypnogram** | The night's sleep-stage timeline (Core/Deep/REM/Awake), one row per segment in `mart_sleep_stages`. |
| **Sleep efficiency** | `100 · time_asleep / time_in_bed` (%). |
| **Composite sleep score** | [0,100] weighted blend of efficiency, REM%, deep% vs. targets minus a fragmentation penalty. |
| **Holt's linear method** | Level + trend exponential smoothing (no seasonality); implemented in pure SQL via the `holt_forecast` macro. |
| **Date spine** | A contiguous `generate_series` of days so zero-activity days count as 0 (not "missing") in rolling windows. |
| **Source priority** | Multi-device dedup order: Apple Watch > iPhone > third-party, applied once in staging. |
| **Two-level idempotency** | File-level (SHA256 ledger in `file_inventory`) + row-level (`ON CONFLICT`) dedup in one transaction; re-runs are no-ops. |
| **z-score / anomaly band** | `(value − rolling_mean) / rolling_std` over a trailing 28-day window; `|z| > 2` flags an anomaly. |

---

*Generated 2026-05-31 from `docs/artifacts-plan.md` (Tier-1). Regenerate the mart
sections when any mart schema changes; regenerate §1–§2 **in lockstep with all
three consumers** when the `mart_recovery_state` contract changes.*
