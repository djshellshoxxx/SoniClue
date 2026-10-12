# 21 Multi-agent coordination

## 1 Roles

* **Coordinator** (one session): owns the canonical specs (`docs/specs/`), `domain/model.py` (shared contracts), the decision register, task ledger (`matrices/backlog.csv`), integration order, audit findings, release scope and the final report.
* **Workers**: own one task each, with exclusive file ownership.

## 2 Ownership map

| Area | Paths | Owner rule |
|---|---|---|
| Shared contracts | `src/sonicclue/domain/`, `docs/specs/schemas/`, `docs/specs/contracts/` | coordinator only; changes need a schema version decision + regenerated schemas + migration plan |
| Numerics | `src/sonicclue/dsp/`, `analysis/` | one worker at a time; invariant tests must stay green |
| Acquisition / sync / sensors | `acquisition/`, `sync/`, `sensors/` | one worker each |
| Diagnostics + procedures | `diagnostics/`, `procedures/` | one worker (rules and procedures co-evolve) |
| Storage | `storage/` | one worker; migrations coordinator-approved |
| App + CLI | `app/`, `cli/` | one worker |
| GUI | `gui/` | one worker per screen file |
| Packaging / CI | `packaging/`, `.github/` | one worker |

## 3 Assignment format

Task ID · objective · owned files · required references (REQ/spec/CON/INV/ADV ids) · dependencies · public contracts touched · permitted changes · acceptance tests (test ids/commands) · expected output (summary, changed files, tests run, unresolved issues, affected contracts) · integration procedure (branch `claude/<task>-<session>`, PR to `main`, rebase on main, full suite before merge).

## 4 Git and PR rules

Task-linked short-lived branches; small cohesive PRs; contracts merged before dependent modules; the full suite plus contract checks run before merge; the combined branch revalidated after merge; superseded PRs closed with a recorded reason; no stranded branches (the final report lists every branch and PR disposition). This environment's CLI `git push` lacks credentials for this repository, so commits are pushed through the GitHub API (spec 25 section 1).

## 5 Token efficiency

Send workers only their owned files, the relevant spec section and the contract ids. Reuse `docs/specs/` rather than repeating research. Return structured summaries. Close idle workers.
