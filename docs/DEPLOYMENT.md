# Deployment guide

This document covers how to deploy the Streamlit app to the internet
so it can be shared as a portfolio link. The pipeline has three moving
pieces and each can sit in a different place:

| Piece | What | Where it can live |
| --- | --- | --- |
| **Streamlit app** | Reads from `analytics_marts.*`, renders pages. | Streamlit Community Cloud (free), Fly.io ($0–5/mo), Railway ($5/mo). |
| **Postgres** | Holds `raw.*`, `analytics_*.*`. | Supabase free tier, Neon free tier, Railway Postgres, Fly Postgres. |
| **Ingest + dbt** | Loads CSVs, runs `dbt build`. | Stays local on the operator's Mac for now; future option: Prefect Cloud or a GitHub Actions cron. |

The simplest free-or-cheap combo for a portfolio demo:

> **Streamlit Community Cloud** (app) + **Supabase** or **Neon** (Postgres) + **local Mac** (ingest + dbt).

The rest of this doc covers that path end-to-end. Alternatives (Fly,
Railway, self-host) are footnoted where the steps diverge.

---

## 0. What needs to be true before you start

- The app already runs locally: `uv run streamlit run app/home.py` works against your docker compose Postgres.
- Your `data/raw/` has at least one real export so the cloud database has something interesting to show.
- You're on `main` with all marts built.

If any of the above isn't true, stop here and finish local setup
(`README.md` → "Local setup") first.

---

## 1. Provision a managed Postgres

### Option A — Supabase (recommended for free tier)

Supabase gives you a Postgres 15+ instance with a generous free tier
(500 MB, 2 GB egress/month). Plenty for personal-scale data.

1. Sign up at https://supabase.com → create a new project.
2. Pick a strong DB password, save it in your password manager.
3. Once provisioned, **Settings → Database** → copy the **Connection String** (URI mode). It looks like:
   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```
   Note the port — Supabase uses `6543` for the pooler. If you hit transaction-mode issues with dbt's metadata calls, switch to the **session-mode** connection string (port `5432`) under the same settings page.
4. Locally, on your Mac, point a temporary env var at it:
   ```bash
   export DATABASE_URL="postgresql+psycopg://postgres.<...>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"
   ```
   Note the `+psycopg` driver suffix — SQLAlchemy needs it for psycopg 3.

### Option B — Neon

Neon is similar but uses branching as its differentiator. The free tier
includes a primary database + storage. Sign up at https://neon.tech,
create a project, copy the connection string from the dashboard.

### Option C — Railway

Railway lets you provision Postgres alongside the app on one account.
Cheapest path if you also want app hosting on Railway. ~$5/mo starter.

---

## 2. Initialize the raw schema in the managed Postgres

The cloud Postgres starts empty. Apply the same init script you ran
locally:

```bash
psql "$DATABASE_URL" -f scripts/init_raw_schema.sql
```

Confirm:

```bash
psql "$DATABASE_URL" -c "\dn"   # should list 'raw'
psql "$DATABASE_URL" -c "\dt raw.*"
```

Expected: `raw.file_inventory`, `raw.quantities`, `raw.workouts`, `raw.categories`.

---

## 3. Cold-start dataset import

Load your existing local data into the cloud Postgres. Run the loaders
end-to-end with the cloud `DATABASE_URL` set:

```bash
# Already exported (still in your local env after step 1)
echo "$DATABASE_URL" | head -c 40   # sanity check; should show the cloud URL

uv run python -m ingest.flows.weekly_load
```

This:
1. Walks `data/raw/` and runs each loader against the cloud Postgres.
2. After load, runs `dbt build` end-to-end against the cloud Postgres
   (you need `transform/profiles.yml` to read `DATABASE_URL` — see step 4).
3. The two-level idempotency contract means re-running is a no-op:
   the file ledger short-circuits files you've already loaded, and
   `ON CONFLICT DO NOTHING` drops duplicate rows.

Verify:

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM raw.quantities;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM analytics_marts.mart_recovery_state;"
```

You should see your real numbers (hundreds of thousands of HR samples,
tens of recovery-state rows, etc.).

---

## 4. Point dbt at the cloud Postgres

`transform/profiles.yml.example` already reads from env vars (see PR
#4). For the cloud deploy, either:

**a)** Set the individual env vars in your shell (`POSTGRES_HOST`,
`POSTGRES_USER`, etc.) — same names CI uses; the example file picks
them up automatically.

**b)** Or replace the host/port/user/password/dbname directly in
`transform/profiles.yml` (local-only; gitignored). Cleanest if you'll
be running dbt from your Mac against cloud Postgres often.

Either way, `uv run dbt debug --project-dir transform --profiles-dir transform`
should report a green connection to the cloud.

---

## 5. Deploy the Streamlit app

### Streamlit Community Cloud (recommended)

1. Go to https://share.streamlit.io and sign in with GitHub.
2. **New app** → pick the `ksdisch/personal-health-elt` repo, branch `main`, main file `app/home.py`.
3. **Advanced settings → Secrets** — paste a TOML block:
   ```toml
   POSTGRES_HOST = "aws-0-<region>.pooler.supabase.com"
   POSTGRES_PORT = "6543"
   POSTGRES_USER = "postgres.<project-ref>"
   POSTGRES_PASSWORD = "<your-password>"
   POSTGRES_DB = "postgres"
   ```
   Same names the code reads via `os.getenv`. Streamlit exposes them as env vars at runtime.
4. **Deploy**. First build takes 5–10 min (it has to install `dbt-postgres`, pandas, sqlalchemy, etc.).
5. Once live, you'll get a URL like `https://ksdisch-personal-health-elt-app-home-xxxx.streamlit.app`.
6. **Update the README** "Live app" link with that URL (see [PR README live-app URL fill-in](../BACKLOG.md)).

### Fly.io (alternative — full control)

```bash
brew install flyctl
fly auth signup
fly launch              # generates fly.toml; pick the default app + region
fly secrets set POSTGRES_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... POSTGRES_PORT=...
fly deploy
```

You'll need a small `fly.toml` and probably a `Dockerfile` that runs
`streamlit run app/home.py --server.port 8080 --server.address 0.0.0.0`.
Free tier covers it for a personal portfolio.

### Railway (alternative — easy bundle)

Connect the GitHub repo at https://railway.app, set env vars in the
service settings, hit deploy. Railway also offers managed Postgres on
the same dashboard if you'd rather not split across two providers.

---

## 6. Redeploy path

### Streamlit Community Cloud

Auto-deploys on every push to `main`. No action needed beyond `git push`.

### Fly.io

```bash
fly deploy              # builds the Docker image, pushes, swaps
```

### Railway

Connected GitHub deploys on push; otherwise `railway up` from the CLI.

### Redeploy on `DATABASE_URL` rotation

If you rotate the Supabase / Neon password (recommended quarterly):
1. Update the secret in Streamlit Cloud / Fly / Railway.
2. Update your local `.env` so ingest still works.
3. No code change.

---

## 7. Recurring ingest after first deploy

The ingest pipeline is still local-first. Easy options to make it
recurring without a server:

- **Manual**: drop a fresh CSV export into `data/raw/`, run `uv run python -m ingest.flows.weekly_load`. The Prefect retry + alert wiring from PR #8 means transient failures show up loudly.
- **macOS launchd** or **cron**: schedule the same one-liner weekly. Sample plist or crontab line:
  ```cron
  0 11 * * 0 cd /Users/<you>/Projects/personal-health-elt && /opt/homebrew/bin/uv run python -m ingest.flows.weekly_load >> /tmp/health-load.log 2>&1
  ```
- **Prefect Cloud (future)**: deploy the `weekly_load` flow there and have it pull CSVs from a cloud blob store. Out of scope for the current portfolio deploy.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `dbt debug` fails with SSL error | Add `sslmode: require` to `profiles.yml` (Supabase/Neon enforce TLS). |
| Streamlit Cloud build hangs on `dbt-postgres` | Pin Python via `runtime.txt` (3.12) and add a `packages.txt` with `libpq-dev` if needed. |
| Source freshness errors after redeploy | Expected for first 7 days if you haven't re-ingested; not a code issue. |
| `analytics_marts.*` empty after deploy | You forgot step 3. Run the ingest pipeline against cloud DATABASE_URL. |
| App loads but pages are blank | Check `app/lib/queries.py` is hitting `analytics_marts.*`, not `raw.*`. |

---

## 9. Cost expectations

| Stack | Monthly cost (small / personal scale) |
| --- | --- |
| Streamlit Cloud + Supabase free + local ingest | **$0** |
| Streamlit Cloud + Neon free + local ingest | **$0** |
| Fly.io + Fly Postgres | ~$0–5 (free allowance covers most personal usage) |
| Railway + Railway Postgres | ~$5–10 |
| Self-host (Hetzner/DO + docker-compose) | $5–10 |
