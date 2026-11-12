# Queued preview lifecycle and controls

Tooling version `queued-preview-v1`; managed runtime schema `mcosu-flat-runtime-v2`.
The game package format remains 1. The tooling version is independent of the
game source SHA, package ID and executable SHA-256. Change this map alongside
any lifecycle, command, retention, or state schema change. The corresponding
Windows regressions are in [test_runtime.py](tests/test_runtime.py).

## How a release reaches the preview

Feature owners identify exact commits. The coordinator selects a combined
committed revision; `build.py build` and `build.py package` produce the same
verified immutable package as before. The coordinator stages that package in
the existing preview. A staged package is independent of the input directory
after staging succeeds. The package ID hashes its manifest; the source commit
and executable digest are distinct fields. This flow does not require rebuilding
the game when only the launcher/controller changes.

Run the commands below as `python preview-runtime.py <command> --runtime <path>`
in an installed preview, or `python tools/runtime/runtime.py ...` from source.

| Command | Policy and outcome |
| --- | --- |
| `stage --package <directory> [--replace]` | Validate and copy while the game runs. Replace a different pending release only on request. Same pending ID keeps its hold; same installed ID leaves history alone. |
| `status` | Available during play. Shows controller version, current/previous/known-good package and source/EXE identities, pending provenance, last outcome, backup path, active images, recovery and defaults. A journal makes the installed pointer provisional. |
| `launch [--dry-run] [--defer-queue] [-- <game args>]` | Promote before launch and after this launcher's own zero game exit. `--defer-queue` disables both edges for this launch; dry-run does neither. The game uses the preview cwd and keeps its own exit code. |
| `retry` / `cancel` | Explicit idle retry (revalidates and takes a new backup) / discard pending intent. Cancellation can run during play. Interrupted install journals require `recover` first. |
| `pin` / `unpin` | Explicitly mark the verified installed bundle as known-good, or remove the pin, while idle. A zero exit never marks acceptance. |
| `rollback --to previous\|known-good --acknowledge-state-risk` | Switch immutable bundles while idle. Cancel any pending release first. Current preferences, scores and cache stay in place. |
| `enable-queue` / `disable-queue` | Idle schema migration or downgrade; downgrade requires a clear journal, no pending release and no pin. Existing writable data stays in place. |
| `update --package <directory>` | Existing immediate idle path. Cancel any pending release before changing bundles. The queued promotion backup policy does not apply to an immediate update. |
| `inspect` / `recover` | Existing idle inspection / restore pre-transaction assets and pointers. Recovery never restores saved data or rearms a failed candidate. |

## Source map and invariants

All controller functions below are in [runtime.py](runtime.py); the launcher
entry point is [Launch-preview.cmd](Launch-preview.cmd).

- `runtime_lock`, `locked`, `queue_lock`: byte 0 guards installation and the
  launcher-managed child lifetime; byte 1 guards queue/store mutations. Order
  is install then queue where both are needed. No queue lock is held during play.
  A busy queue refuses concurrent commands. If a stage is still in progress at
  normal exit, its unpublished candidate waits for the next launch.
- `queue_action`, `store_bundle`: validate an incoming manifest and copy exact
  leaves into the content-addressed store before atomically writing `queue.json`.
  Input paths are provenance only; the private copy is revalidated at promotion.
- `game_launch`, `promote`, `reconcile`: a prelaunch failure with verified old
  assets and no journal still allows the old game to open; the outcome says it
  was held. Unresolved transactions block launch. Nonzero game exit holds a
  queued candidate observed at exit. A failed process start or killed launcher
  has no post-exit promotion; an eligible queue can still promote before the
  next launch once the runtime is idle. No process is stopped by the controller.
  `queue.json` records the exact candidate, reason and detail of the last attempt.
  A process interrupted after journal commit reconciles as promoted; otherwise
  it stays held for explicit recovery/retry. No automatic retry loop.
- `saved_backup`: just before a changed queued promotion, publish one atomic
  `.mcosu-runtime/last-saved-state.zip`, replacing the prior ZIP only after the
  new copy verifies. The ZIP contains `backup.json` with file SHA-256 values and
  `state/` copies of `cfg/` (including profiles and their backup/temp files),
  scores, collections, star cache and `version.txt` if present. Default hard cap:
  512 MiB of saved input. Screenshots, unknown files and the external library
  stay untouched and outside the ZIP. An interrupted write can leave one private
  temporary ZIP, replaced by the next attempt. Backup failure holds the queue
  before changing installed assets. Backup retention is separate from bundles.
- `transact`, `recover_locked`, `collect`: installation uses the existing journal
  and verified immutable leaves. Hold current, previous, one explicit pin, and
  one pending ID; equal IDs share the same bundle. No pruning with a journal
  present. Cleanup only removes unreferenced, validated package trees; keep
  active images and unknown or unverifiable entries for operator inspection.
- `status`, `managed`: state and package manifests give live identity. A legacy
  controller refuses a v2 marker before it can prune queue/pin references. After
  migration use only the new controller for this runtime.

Rollback does not restore the ZIP. If you deliberately need old saved data,
close the game, keep a separate copy of your current state, extract the ZIP to
a separate directory, verify hashes against `backup.json`, then copy only the
saved files you intend to restore. Game data format compatibility across
versions remains unverified. This is a single-user, local Windows workflow;
coordinate external game starts/manual writes and use `status` before acting.

## Install candidate and migrate an existing preview

These are coordinator steps; run on an idle runtime. Use the controller and
launcher from the **same** reviewed source revision. The launcher config file
`preview-python.txt` is one line: the absolute path of Python 3.13 or later.

1. Run `status` with the new source controller. Confirm installed identity and
   no active image/recovery. Back up the existing launcher, `preview-runtime.py`,
   any Python path config, and `PREVIEW.json` outside the runtime. Record hashes
   of the current/previous bundles and writable state. Keep game paths intact.
2. Run the source controller's `enable-queue` for the exact runtime. It acquires
   the idle install lock before upgrading the marker. Copy the new `runtime.py`
   as `preview-runtime.py`, new `Launch-preview.cmd`, and the Python path file to
   the same preview root. The old launcher process cannot pick up new Python code
   at exit. If a legacy game is active, let the user finish first; no waiter.
3. If `PREVIEW.json` is the recognized legacy receipt (its `package_id` and
   `exe_sha256` match the live `status`), archive its bytes under a distinct
   history path and replace it with a static pointer containing no current
   package/source/hash fields. For example:
   `{"kind":"mcosu-preview-status-pointer-v1","controller":"preview-runtime.py","command":"status","runtime":"."}`.
   Preserve unknown metadata instead of overwriting it; stop and reconcile
   before rollout if an existing receipt cannot be identified.
4. Verify controller and launcher hashes, unchanged saved-state and live image
   bytes, then run `Launch-preview.cmd --dry-run` from another cwd and check
   `status`. Do not stage a release merely to test migration.

To revert only the controller: close the game, inspect/recover any journal,
cancel the queue and unpin explicitly if present, then `disable-queue`. Restore
the prior launcher and controller files. Keep the static identity pointer or
make a new receipt from verified installed state; never reinstate an old receipt
as current after an actual game update. Keep backups until reviewed separately.
