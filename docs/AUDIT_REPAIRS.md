# Audit repairs: local file safety

This first repair phase addresses the local file-operation and recovery problems
in the 13 November 2026 audit. Findings outside this phase remain open.

| Finding | Progress |
| --- | --- |
| F01: filename-based omission | Organization retains named variants. The legacy detection helper compares full content digests instead of name patterns. |
| F02: destination collisions | Organizer Copy and Move publish exclusively and choose a digest suffix for collisions. Classification and the CLI duplicate handler still need migration to this shared executor. |
| F03: partial/unverified copies | Organizer transfers write privately, verify SHA-256 and size by reading back the output, check source stability, then publish. Move removes its source only after verification and publication. |
| F05: destructive undo | New records contain output identity. Undo refuses edited/replaced outputs, occupied restore paths, and removal of a copy whose original content is no longer available. Old path-only journals require manual review. |
| F06: journals and retry | UUID sessions, atomic journal replacement, intent before organizer publication, per-action recovery state, active-session exclusion and retryable conflicts are implemented. Other legacy mutation callers still record operations afterward and need migration. |
| F07: compression overwrites | Direct compression refuses source aliases and existing outputs. Directory compression rejects overlapping roots. Encoders write privately; failed output is removed and publication never replaces another file. |
| F34: threshold zero | The scan and organize forms preserve zero instead of substituting five. The obsolete filename-skip option is removed from the UI and CLI. |

Transfers and undo coordinate cooperating app processes with POSIX advisory locks.
Organizer workers share one journal scoped to the job. A failed journal write
propagates instead of being silently treated as successful recovery bookkeeping.
Completed undo actions are persisted individually; conflicts keep the remaining
journal available through the existing API.

Validation at this phase: 62 Python tests, including the 16 existing API/workflow
tests, plus Ruff and a frontend production build. The added regressions cover separate-process name collisions,
disk-full errors, corrupted copies, changed sources, occupied restore paths,
partial undo retries, completion-write failures, abrupt process exits at three
transfer boundaries, and compression failures/races. All fixtures are disposable.
The 46 tests added by this phase also run from an export of the committed tree.

## Current limits and next repairs

- Publication currently requires hard-link support on the destination filesystem.
  Unsupported filesystems fail without replacing a destination or removing a Move
  source. FAT/exFAT support needs another verified, atomic non-replacing primitive.
- Locks coordinate Clean_Backup operations. They cannot exclude unrelated editors
  or tools; revision checks detect changes at verification boundaries.
- Abrupt termination can leave hidden `.clean-backup-*.partial*` staging files.
  Recovery preserves them; automatic discovery and cleanup are still needed.
  Unpublished staging files are not successful final outputs.
- The compression encoder's metadata, animation, HDR and stream-preservation
  limitations (F08) are unchanged. The new publication boundary does not certify
  the encoded media's semantic fidelity.
- Perceptual matching and automatic perceptual omission remain heuristic. This
  phase does not repair F11–F16 or make a safe-exact-mode claim.
- Prioritize server-owned deletion plans (F04), API authentication/origin/root
  boundaries (F09), cloud object identity (F27), and safe Docker build inputs
  (F37) next. These high-priority findings remain open.
- Migrate classification, CLI duplicate handling and Trash to the executor, fix
  classification catalog/undo contracts, and add an explicit resume/reconciliation
  interface. Recovery currently offers safe undo, not automatic forward resume.
- API job outcome reporting (F17), other workflow/provider/watcher defects,
  distribution, dependency triage and UI changes remain separate work.

There is no throughput claim or cross-platform certification for this phase.
Existing uncommitted CI, README, demo and test changes were left out of its commits.
