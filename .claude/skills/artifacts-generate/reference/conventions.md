# Default conventions for generated artifacts

Used by the `artifacts-generate` skill when `docs/artifacts-plan.md` doesn't specify otherwise. If the repo has an established convention (e.g., ADRs under `docs/architecture/decisions/`), **prefer the repo's convention** over these defaults.

## Default paths

| Artifact          | Path                                                |
|-------------------|-----------------------------------------------------|
| ADR               | `docs/adr/000N-short-title.md`                      |
| Design doc / RFC  | `docs/design/<feature-slug>.md`                     |
| PRD               | `docs/prd/<feature-slug>.md`                        |
| Runbook           | `docs/runbooks/<operation-slug>.md`                 |
| Playbook          | `docs/playbooks/<scenario-slug>.md`                 |
| Postmortem        | `docs/postmortems/YYYY-MM-DD-<incident-slug>.md`    |
| SLI/SLO/SLA       | `docs/reliability/slos.md`                          |
| On-call doc       | `docs/oncall.md`                                    |
| Diagram (Mermaid) | `docs/diagrams/<name>.mmd` or inline in Markdown    |
| ERD (DBML)        | `docs/diagrams/erd.dbml`                            |
| README            | `README.md` (repo root)                             |
| CHANGELOG         | `CHANGELOG.md` (repo root)                          |
| CONTRIBUTING      | `CONTRIBUTING.md` (repo root)                       |
| Code of Conduct   | `CODE_OF_CONDUCT.md` (repo root)                    |
| LICENSE           | `LICENSE` (repo root)                               |
| `.env.example`    | `.env.example` (repo root)                          |
| PR/issue templates| `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/*.md` |
| Onboarding doc    | `docs/onboarding.md`                                |
| Glossary          | `docs/glossary.md`                                  |
| Data dictionary   | `docs/data-dictionary.md`                           |
| API docs          | `docs/api/` (multi-file) or `openapi.yaml` (root)   |
| Roadmap           | `docs/roadmap.md` or `ROADMAP.md` (root)            |
| Backlog           | `BACKLOG.md` (root) or `docs/backlog.md`            |

## ADR numbering

- Four-digit zero-padded numbers: `0001-`, `0002-`, `0099-`, `0100-`.
- **Append-only.** If a decision is superseded, mark the old ADR's status as `Superseded by ADR-NNNN` and write a new ADR — don't rewrite history.
- Status values: `Proposed`, `Accepted`, `Deprecated`, `Superseded by ADR-NNNN`.
- Title slug: lowercase kebab-case, focused on the decision noun (`caching-strategy`, not `we-decided-to-use-redis`).

## Diagram defaults

| Use case                          | Format     | Notes                                    |
|-----------------------------------|------------|------------------------------------------|
| Architecture (C4, sequence, etc.) | Mermaid    | Inline in Markdown or `.mmd` file        |
| Data model (ERD)                  | DBML       | Lives at `docs/diagrams/erd.dbml`        |
| Pipeline / DAG                    | Mermaid    | Use `flowchart TD` or `graph LR`         |
| Lo-fi sketches / brainstorms      | Excalidraw | Export to `.png` + commit `.excalidraw`  |
| UI mockups                        | Figma      | Link from Markdown, don't embed          |

**Default to Mermaid.** Reach for DBML, Excalidraw, or Figma only when the artifact actually needs that format.

## Filename slugs

- **Lowercase kebab-case:** `caching-strategy`, not `Caching_Strategy` or `cachingStrategy`.
- **Under 40 characters** where possible.
- **Dates in ISO format:** `YYYY-MM-DD-incident-slug.md` (sorts chronologically by default).
- **No spaces, no special characters** beyond hyphens.

## Postmortem dates

- Use the **date of the incident**, not the date the postmortem was written.
- Format: `YYYY-MM-DD-<incident-slug>.md`.
- Multi-day incidents: use the start date.

## Diagram embedding

- **Mermaid in Markdown:** prefer inline via fenced ` ```mermaid ` blocks for diagrams under ~20 nodes.
- **Standalone `.mmd` file:** for larger diagrams or anything reused across multiple docs. Reference from Markdown via a link, or use a Mermaid pre-renderer in CI.
- **Always include a one-line caption** above the diagram describing what it depicts.

## CHANGELOG format

Default to **[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)** unless the repo has a different convention:

```
# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]
### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security

## [1.2.0] - YYYY-MM-DD
...
```

## Versioning

- **SemVer (`MAJOR.MINOR.PATCH`)** for libraries and SDKs.
- **CalVer (`YYYY.MM.DD` or `YY.MM`)** for applications and services where there's no public API to break.
- **No versioning** is fine for personal/internal repos — but say so in the README rather than leaving it ambiguous.

## Per-repo overrides — how to detect them

Before applying these defaults, scan for repo-local conventions:

- Existing `docs/adr/`, `docs/architecture/decisions/`, `docs/decisions/`, or `adr/` directories → use the existing path
- Existing `.adr-dir` file → respects [adr-tools](https://github.com/npryce/adr-tools) convention
- Existing CHANGELOG with a clear non-Keep-a-Changelog format → match the existing format
- Existing diagram conventions (e.g., all PlantUML) → match
- Custom diagram tooling configured in CI → match what CI expects
