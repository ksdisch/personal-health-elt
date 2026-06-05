# Canonical engineering artifacts taxonomy

Reference list for the `artifacts-audit` skill. The audit classifies each artifact below as ✅ PRESENT / ⚠️ STALE-THIN / 🟢 RECOMMENDED / 🟡 OPTIONAL / ⛔ NOT APPLICABLE for the repo under review.

## REPO HYGIENE

- `README.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `LICENSE`
- `CHANGELOG.md`
- `.env.example`
- PR / issue templates
- `Makefile` or `Taskfile` or `justfile`

## DECISION & DESIGN

- **ADRs** (Architecture Decision Records) — one per significant, hard-to-reverse decision
- **Design Doc / RFC / Tech Spec** — proposal for how to build something non-trivial
- **PRD** — what & why, from the product/user angle
- **Postmortem / RCA** — written after incidents (uses the postmortem template in Ops below)

## PLANNING

- Roadmap (now / next / later)
- `BACKLOG.md` (or external tracker), user stories
- Sprint plan, WBS, RACI matrix, OKRs, Gantt, Kanban

## DIAGRAMS

Default to **Mermaid**. Use **DBML** for ERDs in data-heavy repos. Use **Excalidraw** for lo-fi sketches. Use **Figma** only for UI mocks.

- **C4:** Context / Container / Component / (rarely Code)
- **Behavior:** sequence diagram, flowchart, state machine, swimlane, activity
- **Structure:** UML class / component / deployment
- **Data:** ERD, data flow diagram (DFD), data lineage, dimensional model (star/snowflake), pipeline/DAG diagram
- **Infra/UX:** network/topology, cloud architecture, wireframes/mockups

## OPS & RELIABILITY

- **Runbook** (per recurring/risky operation)
- **Playbook** (per scenario)
- **Postmortem template**
- **SLI / SLO / SLA** doc
- **On-call / escalation** doc

## KNOWLEDGE

- Onboarding doc
- API docs (OpenAPI / Swagger)
- Data dictionary
- Wiki
- Glossary
