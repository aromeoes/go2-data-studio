# Publication checkpoint and follow-up work

This public repository starts from a clean snapshot of the local Go2 Data Studio
application. The prior local commit history is retained separately and is not
published. Machine-specific runtime paths and robot serial defaults have been
removed. Deployment options are environment variables documented in README.md;
.env.example documents robot and HumanCLI credentials without values.

Publication checks on 2026-09-22 passed 100 backend tests, 14 frontend tests,
Ruff, shell syntax checks, the production build and verification of all 133
vendored upstream files. Credential-pattern findings were reviewed as test fixtures. Automated and replay checks do not establish physical
navigation reliability or readiness for unattended operation.

## Follow-up work

* Cloud: adapt the official Python CloudData client for background uploads and
  progress reporting. Preserve consistent SQLite snapshots, segment metadata,
  account reconciliation and persistent backup badges. Review the full download
  verification policy explicitly when changing the adapter.
* Recording: evaluate the standard TransportRecorder around the SqliteStore
  already used here. Preserve start/stop segmentation and diagnostics, and check
  pose metadata compatibility with map jobs. Changing the recorder alone is not
  evidence that recording interruptions or movement slowdown are fixed.
* Navigation already uses the DimOS planner, costmap and frontier explorer.
  Preserve control authority, cancellation, stale-sensor checks and posture
  guards when adopting further upstream components.
* Validate the selected HumanCLI provider/model and physical operation with an
  operator present before activating updates on a robot.

These refactors are follow-up work, not changes made for publication. Publication
does not restart the running application or issue robot commands.
