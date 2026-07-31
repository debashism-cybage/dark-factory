# Legacy Code

This folder contains the original Lambda source code that was edited directly
in the AWS Lambda console before the project was refactored.

These files are kept for reference only. The active code lives in:

- `../shared/` — reusable shared libraries
- `../agents/` — refactored agent handlers
- `../workflow-starter/` — API Gateway entrypoint

## Folder Mapping

| Legacy Folder | Replaced By |
|---|---|
| `approval-handler/` | _(not yet implemented in new architecture)_ |
| `architecture-agent/` | `../agents/architecture/` |
| `development-agent/` | `../agents/development/` |
| `planning-agent/` | `../agents/planning/` |
| `release-agent/` | `../agents/release/` |
| `validation-agent/` | `../agents/validation/` |
| `workflow-starter/` | `../workflow-starter/` |
| `misc/` | _(reference docs, not deployed)_ |

## Safe to Delete

This entire `_legacy/` folder can be deleted once the new architecture
is deployed and verified in production.
