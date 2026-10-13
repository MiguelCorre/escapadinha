# Triage labels

| Label | Meaning |
|---|---|
| `spec` | The issue is a spec (links to `docs/specs/`). |
| `ready-for-agent` | Fully specified; an agent may pick it up without further triage. |
| `in-progress` | An agent or Miguel is working on it. |
| `blocked:miguel` | Waiting on an action only Miguel can do (listed in *Ações do Miguel*). |
| `needs-decision` | A product decision is open; do not start. |
| `M1`…`M6` are **milestones**, not labels. |

Flow: `needs-decision` → `ready-for-agent` → `in-progress` → closed. `blocked:miguel` may be added at any point and removed once the action is done.
