# Modularization verification

Final source verification for the 34-slice Danbooru modularization sequence,
2026-09-19. This records tested behavior, not a packaged release certification.
The runtime version remains defined by `backend/product.py`.

## Results

| Area | Evidence | Result |
| --- | --- | --- |
| Python regression suite | `python -m pytest -q` | 464 passed, 2 platform skips, 178 subtests |
| Frontend types/templates | `npm --prefix frontend run check` | Zero errors and warnings |
| Store compatibility | `tests/frontend_stores.mjs` | 49 identical exports; legacy keys, normalization, derived state and rollback |
| API compatibility | `tests/frontend_api.mjs` | 100 requests, 7 URLs, 92 method identities, errors and suite isolation |
| Registration | `tests/frontend_registry.mjs` | Installed, absent and additional-owner discovery/actions/fallback |
| Settings catalog/coordination | `tests/frontend_settings.mjs` | 11 sections, 31 search entries, isolated owner coordination |
| Import boundaries | Python boundary tests; `tests/frontend_boundaries.mjs` | Shared/module and compatibility-barrel checks pass |
| Lifecycle/failure | `test_module_lifecycle.py`, `test_module_failure_http.py`, `test_module_guards.py` | Disable/enable ordering, worker drain/cancel, failure isolation/retry and route guards |
| Schema/upgrade | `test_user_schema_ownership.py`, `test_danbooru_index_migrations.py`, `test_release_layout.py` | Additive identity migration, legacy paths, Files-only initialization and preservation fixtures |
| Recovery | `test_local_recovery.py`, `test_backup_bundle.py` | Preserved checkpoints, conflicts, copy failures, rollback, WAL locks, attachment publication and original-media exclusion |
| Pipeline/credentials | `test_pipeline_ownership.py`, `test_credentials.py`, `test_credential_ownership.py` | CLI/import compatibility, offline phases, lock identity, mocked vault rollback/redaction and helper dispatch |
| Delivery | `test_delivery.py`, release/source-launch tests, isolated portable check | Installed/absent declarations, spec evaluation and simulated frozen resource checks |
| Source syntax | `compileall` | Passed |

## Browser verification

Each run builds the current frontend into scratch space and starts a disposable
backend/home. The final run used installed Windows Edge against a WSL backend.
No API traffic is sent to Danbooru. Reports, traces and screenshots are saved in
the runner's requested output directory.

| Suite | Passed groups | Coverage |
| --- | ---: | --- |
| `modularization` | 10 | Timed drawer/sidebar entry and exit, rapid reversals, delayed grip reveal, drag/keyboard position persistence, scrolling, independent grid sizes, disabled/enabled Settings, reduced motion |
| `danbooru` | 5 | Synthetic populated image library, spotlight advance, independent Home lanes and pause/resume, detail zoom/drag, favorite reconciliation, Profile/Collections/Challenge/Tags reachability |
| `backup` | 8 | Owner catalog, delayed estimate ordering, selection saves, real scratch backup/restore, whole-database confirmation, attachments and rollback feedback |
| `settings` | 6 | Lazy owner loading, drafts and preference keys, all sections, search highlighting, overlays, polling and teardown |
| `absence` | 4 | Both Danbooru source folders absent; real Files registration/scan/browse/search/reload, stale preference fallback, Settings, absent endpoints/storage/tables, original fixture bytes preserved |

The motion fixture now starts observing sidebar width before clicking Browse.
Waiting for visibility before observation could miss the short transition across
the WSL/browser boundary. Assertions still require intermediate frames and the
final position. No application animation was changed. All four older suites now
accept `PLAYWRIGHT_CHANNEL`, matching the absence suite, so an installed browser
can be selected without downloading another browser.

## Repeating the checks

Use the project's Python environment and installed frontend dependencies:

```sh
.venv/bin/python -m compileall -q backend scripts app.py
.venv/bin/python -m pytest -q
npm --prefix frontend run check
node tests/frontend_stores.mjs
node tests/frontend_api.mjs
node tests/frontend_registry.mjs
node tests/frontend_settings.mjs
node tests/frontend_boundaries.mjs
```

Run the browser runner once for each suite listed above, choosing a new output
directory each time. For example:

```sh
.venv/bin/python tests/run_modularization_browser.py --script absence --output /tmp/keivotos-final-absence
```

The runner requires Node, Playwright and an available browser; it does not install
them. `--node` selects Node, `PLAYWRIGHT_MODULE` selects an external Playwright
package, and `PLAYWRIGHT_CHANNEL` selects an installed browser. Cross-OS WSL/Windows
execution additionally needs argument/output-path and environment forwarding;
the temporary adapter used for this verification is not a project dependency.

## Remaining verification limits

- Fresh Windows/Linux frozen artifacts were not built or run. Simulated frozen
  paths and evaluated specifications do not prove a working native package.
- Native DPAPI/Secret Service providers were not retested; credential tests used
  disposable manifests and mocked providers. Browser account responses are fixtures.
- External acquisition, long Danbooru jobs, populated artist assets and the full
  video/GIF interaction surface were not exercised by these browser fixtures.
- Migration/recovery tests use synthetic databases/files; no real library was
  migrated, restored or otherwise modified. Real cross-drive Windows behavior
  remains separate platform verification.
- Files-only verification builds/runs the reachable application. Historical
  compatibility barrels still require their owner when imported or independently
  type-checked; the application is prevented from importing them.
- Static import checks cannot prove computed dynamic imports. Hosted CI execution
  awaits the user's push.

The live app server was not restarted. All fixture servers were stopped. No real
media, sidecars, databases or credentials were changed; no dependencies were
installed, external Danbooru requests made, release artifacts created or Git
publication performed. Passing this matrix completes the planned source
verification; it does not certify every untested feature or platform.
