# personal-health-elt — common dev commands.
# Run `just` (or `just --list`) to see all recipes.
# These wrap the commands documented in CLAUDE.md / CONTRIBUTING.md — keep in sync.

set dotenv-load := true   # auto-load .env (POSTGRES_*, API keys) if present

# Show available recipes
default:
    @just --list

# --- setup ---------------------------------------------------------------

# Install / update dependencies
sync:
    uv sync

# Start the Postgres 16 container
up:
    docker compose up -d

# Stop the Postgres container
down:
    docker compose down

# --- quality gate --------------------------------------------------------

# Lint
lint:
    uv run ruff check .

# Auto-format
fmt:
    uv run ruff format .

# Type-check the ingest package (app/ intentionally skipped — see BACKLOG)
typecheck:
    uv run mypy ingest

# Unit tests
test:
    uv run pytest

# Full local gate: lint + typecheck + unit tests + dbt build
check: lint typecheck test dbt-build

# --- dbt -----------------------------------------------------------------

# Validate the dbt project (parse only, no DB writes)
dbt-parse:
    uv run dbt parse --project-dir transform --profiles-dir transform

# Build all dbt models and run their tests
dbt-build:
    uv run dbt build --project-dir transform --profiles-dir transform

# Data-freshness SLI (see docs/reliability/slos.md)
freshness:
    uv run dbt source freshness --project-dir transform --profiles-dir transform

# --- run -----------------------------------------------------------------

# Launch the Streamlit app
app:
    uv run streamlit run app/home.py

# Run the weekly ingest + dbt build flow once (idempotent)
load:
    uv run python -m ingest.flows.weekly_load

# Register the weekly cron deployment and stay running (Ctrl-C to stop)
serve:
    uv run python -m ingest.flows.weekly_load --serve
