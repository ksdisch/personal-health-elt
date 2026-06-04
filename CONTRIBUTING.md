# Contributing

This is a **solo, single-user personal project** (and a portfolio piece) — it isn't
soliciting outside contributions. But it's written so a reviewer or a forker can get
it running and find their way around quickly. For the deeper "why" behind the
architecture, read [`CLAUDE.md`](CLAUDE.md); for the forward plan, see
[`ROADMAP.md`](ROADMAP.md) and [`BACKLOG.md`](BACKLOG.md).

## Prerequisites

- **Python 3.12**, managed with [`uv`](https://docs.astral.sh/uv/) (never
  `pip install` directly).
- **Docker** (Postgres 16 runs via `docker-compose.yml`).
- Optional: [`just`](https://github.com/casey/just) for the command shortcuts below.

## Setup

```bash
uv sync                                   # install deps
cp .env.example .env                      # fill in POSTGRES_* (defaults match docker-compose)
docker compose up -d                      # start Postgres 16
psql "$DATABASE_URL" -f scripts/init_raw_schema.sql   # or use POSTGRES_* / docker exec
cp transform/profiles.yml.example transform/profiles.yml   # point dbt at your Postgres
```

Then load data and build the marts (idempotent — safe to re-run):

```bash
uv run python -m ingest.flows.weekly_load    # load CSVs from data/raw → run dbt build
```

For a cloud deploy (managed Postgres + Streamlit Cloud), see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Dev loop

The local gate — run this before every commit (or `just check`):

```bash
uv run ruff check .                                            # lint
uv run mypy ingest                                             # type-check (app/ skipped — see BACKLOG)
uv run pytest                                                  # unit tests
uv run dbt build --project-dir transform --profiles-dir transform   # models + dbt tests
```

Other commands:

```bash
uv run dbt parse  --project-dir transform --profiles-dir transform   # validate dbt project
uv run dbt source freshness --project-dir transform --profiles-dir transform  # freshness SLI
uv run streamlit run app/home.py                              # launch the app
```

All of the above are wrapped as recipes in the [`justfile`](justfile) — run `just`
to list them.

### Pre-commit hooks

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

`ruff check` + `ruff format --check` run on **commit**; `mypy ingest` runs on **push**
(local `language: system` hooks, so versions never drift from CI).

## Git workflow

- **Feature branches**, prefixed `feat/`, `fix/`, `refactor/`, or `docs/`.
- **Conventional commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`,
  `ci:`) — they drive the [`CHANGELOG.md`](CHANGELOG.md).
- **Never push directly to `main`.** Open a PR; squash-merge.
- **Stage files by name** (`git add path/to/file …`). Never `git add -A` / `git add .`
  — too easy to sweep in `.env`, `data/raw/*.csv`, or `transform/target/`.

## Tests & CI

- **pytest** (`tests/`) — Python unit + Postgres-gated integration tests.
- **dbt tests** — schema tests (`not_null`, `unique`, `accepted_values`) co-located in
  each layer's `schema.yml`, plus singular tests under `transform/tests/`.
- **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs, in order:
  ruff → `mypy ingest` → `pytest --cov` → init raw schema → `dbt parse` →
  `dbt build` against an empty Postgres service container. A test can fail for a
  reason — read the compiled SQL / test source before loosening it.

## Conventions worth knowing

These are load-bearing — see [`CLAUDE.md`](CLAUDE.md) for the full rationale:

- **Loaders are idempotent** (SHA file ledger + `ON CONFLICT`); re-running a load is a
  no-op.
- **Timezones normalize at staging** (UTC → `America/Chicago`), nowhere else.
- **Multi-source dedup priority:** Apple Watch > iPhone > third-party.
- **Strict dbt layering:** `staging → intermediate → marts`. Marts never select from
  `source()` directly.
- **`mart_recovery_state` is a public API** with three downstream consumers — schema
  changes require updating all consumers in lockstep. Don't break it silently.
- **HR zones are config, not code** (`transform/seeds/hr_zones.csv`).
- **Streamlit queries over raw HR samples must be `@st.cache_data`-wrapped** in
  `app/lib/queries.py`.
