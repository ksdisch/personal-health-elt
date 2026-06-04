# Security & data handling

`personal-health-elt` is a **single-user personal pipeline** that processes the
maintainer's own Apple Health data. The source is public for portfolio purposes, but
there is no multi-user deployment and no third-party data. This note documents the
trust boundary, where secrets live, and how to report an issue.

## Data classification & trust boundary

- **The health data is personal and sensitive**, but it is *the maintainer's own*.
  None of it is committed: `data/raw/*` is gitignored (only a `.gitkeep` is tracked),
  and the warehouse lives in a local Docker Postgres.
- **Compute stays local — there is no data-egress step in the core pipeline.** CSVs
  are loaded on the same machine they live on; dbt builds against local Postgres.
- **iCloud trust boundary.** In normal operation the export CSVs route through the
  maintainer's **iCloud Drive** so the iOS export syncs to the Mac (see
  [`docs/automation.md`](docs/automation.md)). That places them in the same personal
  cloud as iCloud Health sync — a deliberate, documented tradeoff, not an egress of
  the pipeline. Zero-cloud alternative: drop exports straight into `./data/raw` over
  USB/AirDrop and unset `HEALTH_EXPORT_PATH`.

## Secrets

All credentials are kept out of git and must **never** be committed:

| Secret | Where | Status |
|---|---|---|
| `.env` (Postgres + all API keys/tokens below) | repo root | **gitignored**, verified never committed |
| `transform/profiles.yml` (dbt → Postgres) | `transform/` | **gitignored**; use `profiles.yml.example` |
| Firebase service-account JSON (`TEMPO_FIREBASE_SA_PATH`) | outside repo (absolute path) | never committed |
| Google Calendar secret iCal URL (`CALENDAR_ICS_URL`) | `.env` only | anyone with it can read your calendar |

`.env.example` documents every variable with **placeholder values only**. If you fork
this, copy it to `.env` and fill in your own.

## Outbound data surface (optional integrations)

The core pipeline does not phone home. Several **opt-in** integrations do send data
out when (and only when) their env vars are set — each no-ops silently otherwise.
This is the honest "data leaves the machine" surface:

- **OpenWeather** (`OPENWEATHER_*`) — sends your lat/lon + dates to fetch weather.
- **Google Calendar** (`CALENDAR_ICS_URL`) — reads your calendar via a secret iCal URL.
- **Pushover** (`PUSHOVER_*`) — sends anomaly-notification text to your phone.
- **Anthropic API** (`ANTHROPIC_API_KEY`, the "Ask" page) — sends your question + the
  mart **schema summary**, and may include **mart values** in results, to the API.
- **Firestore** (`TEMPO_FIREBASE_*`) — one-way push of `mart_recovery_state` (latest +
  last 14 days) to your own Tempo PWA project.

See [`.env.example`](.env.example) for exactly what each one is and how to enable it.

## Reporting a vulnerability

Please report security issues **privately** via GitHub's **"Report a vulnerability"**
(repo **Security** tab → *Report a vulnerability* → private advisory) rather than a
public issue or PR.

> **Maintainer one-time setup:** enable **Settings → Code security → Private
> vulnerability reporting** for the repo so the advisory form is available.

This is a personal project maintained solo on a best-effort basis — expect a
non-committal timeline, but reports are genuinely welcome.

## Supported versions

Only the latest `main` is supported; there are no backports or maintenance branches.
See [`CHANGELOG.md`](CHANGELOG.md) for release history.
