# END Harness v0.1.1 implementation report

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Completed 2026-09-28. Project: **`E:\The End Harness`**. The original report is archived byte-for-byte as `IMPLEMENTATION_REPORT_v0.1.md`. Existing v0.1 runs remain unchanged.

## Implemented corrections

- Finalization now returns a structured partial `RunResult` for ordinary failures. Engine execution/result, trajectory snapshot, trajectory import, journal closure, summary persistence, cleanup, and ordered failure causes are separate. Available Engine results survive finalization failures, including recovery of a native result from END's public trajectory when its own ledger save raises.
- Invalid Unicode is rejected without a second UTF-8 encoding attempt. Unavailable original hashes remain null with reasons; safely escaped diagnostics are explicitly labelled and never substituted as artifact bytes.
- Final-candidate coverage is bound to the real returned Engine candidate, run/trajectory identity, original content hash, and exact tested artifact. Required versus optional and completed versus passed checks are distinct. Full history remains separate. Repeated collections use the latest exact binding and expose conflicts without merging earlier passes.
- Generic `post_acceptance_cycles` now defaults to zero. The offline regression demo explicitly requests one, exercising native Engine C2 → C1 rollback.
- Controlled Engine loading pins its initial path/version/manifest/fingerprint, checks before/after import, rejects prior uncontrolled imports and later source drift, and requires a fresh process after invalidation. No Engine modules are reloaded to bypass provenance checks.
- The focused audit also repaired opaque-judge deadline-result pairing, validator mutation before checker dispatch, receipt-persistence failure dispatch blocking, and unsafe error diagnostics. Existing budgeting, retries, model-judge cloning, receipt validation, and recovery invariants remain in place.

All five requested findings were confirmed. None was rejected as inaccurate. The full triggers, impacts, repairs, source references, regression mapping, and retained limitations are in [AUDIT_v0.1.1.md](AUDIT_v0.1.1.md).

## Actual commands and results

The actual pre-patch baseline was **51 Harness tests passed in 2.715 seconds**, reproduced against the real local Engine before editing. Final verification ran from the requested project location:

```powershell
Set-Location 'E:\The End Harness'
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
$env:PYTHONPATH = 'E:\The End Engine'
& $HarnessPython -B -m unittest discover -s 'E:\The End Engine\tests' -v
& $HarnessPython -B -m end_harness demo --engine-source 'E:\The End Engine' --output output/demo-v011
```

| Verification | Actual result | Saved evidence |
|---|---|---|
| Full Harness suite, including real Engine integrations | **88 passed in 15.382 s** | `output/validation-v011/harness-tests.txt` |
| Unchanged Engine suite | **115 passed in 6.001 s** | `output/validation-v011/engine-tests.txt` |
| Real Engine offline regression/budget/interruption demonstrations | Exit 0 | `output/validation-v011/demo-console.json` |
| New-format CLI inspection | Exit 0, closed history, readable summary, C1 bound coverage | `output/validation-v011/inspect-new.json` |
| Old-format CLI inspection | Exit 0, old history retained; final bound coverage explicitly unavailable | `output/validation-v011/inspect-old.json` |
| Repeated interrupted closure | Both exit 0; unchanged original journal and recovery bytes | `closure-first.json`, `closure-second.json` in the same validation directory |

The 88 tests comprise all 51 previous cases and 37 new regressions: 13 finalization, 12 coverage/default/Unicode, 6 loaded-source provenance, and 6 focused audit boundary cases. Engine integration uses the real local Engine. Fault-injection tests inspect surviving files, use temporary output directories outside Engine source, and clean up afterward. Source-drift tests use disposable Engine copies in separate interpreters. No Engine tests were changed or weakened.

## Real Engine demonstration

Normal run: `output/demo-v011/6ca43c52-50cb-476d-bb2b-66166ca0766d`.

Engine trajectory: `59145076-8840-41ef-ae57-f09834d10316`.

Observed sequence: C0's policy fails the actual bounded checker; C1 passes; C2 removes the healthy-replica invariant and fails; END's own comparator/gate/rollback restores C1. The Engine result remains `ACCEPTED_VERIFIED`, best/final C1, latest C2. The Harness does not force this selection.

Final-candidate evidence coverage:

| Field | Observed value |
|---|---|
| Returned candidate | `(59145076-8840-41ef-ae57-f09834d10316, C1)` |
| Required checks | `deployment.safety` |
| Completed checks | `deployment.safety` |
| Passed checks | `deployment.safety` |
| Failed / errored / unknown / missing | All empty for C1 |
| Receipt | `receipts/e50d8dd8-b183-45d7-a57b-dfe9455f64d2.json` |
| Original UTF-8 content SHA-256 | `f08f251a864b4aeb0123c77aa90d05fe17b3c04754cf6d391e441435f3adbc78` |
| Exact tested artifact SHA-256 | `8a14df0728888358af700670427c5a9b33545c4d2dced952e92ddff3560a9fd4` |

C2's completed FAIL stays in the separate coverage history and receipt store. The run charges 21 model attempts and 3 check attempts; all 21 token usages are unknown, not measured zero. Caller-observed snapshot/import/closure/summary/cleanup outcomes are confirmed. The generic default, separately tested, stops at C1 with 13 model attempts and 2 checks.

Budget-exhaustion run: `output/demo-v011/d2abb104-7686-449e-96ae-de8b52cc0288`. It charges three model attempts, then preserves Harness `model_attempts_exhausted` separately from Engine `EXTERNAL_BLOCKER`.

Interrupted fixture: `output/demo-v011/80d74419-0620-4a9b-80f1-a69bcd0c994e`. Its unmatched call remains `OUTCOME_UNKNOWN`; the 33-byte torn final record is preserved. Closure repeats without executing work or adding duplicate recovery records. The manufactured fixture is labelled; the suite additionally exits an actual Engine subprocess at a provider boundary.

These model/judge responses are **SYNTHETIC fixtures**. The checker executes real bounded transitions over inert JSON. This demonstrates runtime correctness and scoped checks, not improved intelligence, judge accuracy, or production deployment safety.

## Inspection and compatibility

Commands actually exercised:

```powershell
& $HarnessPython -B -m end_harness inspect 'output/demo-v011/6ca43c52-50cb-476d-bb2b-66166ca0766d'
& $HarnessPython -B -m end_harness inspect 'output/demo/953efb95-5f0f-445c-a35b-a56ef637ec3a'
& $HarnessPython -B -m end_harness close-interrupted 'output/demo-v011/80d74419-0620-4a9b-80f1-a69bcd0c994e'
& $HarnessPython -B -m end_harness close-interrupted 'output/demo-v011/80d74419-0620-4a9b-80f1-a69bcd0c994e'
```

Package version is **0.1.1**. New result and coverage payloads use schema **1.1**; existing event-envelope, artifact, receipt, and recovery versions remain unchanged. The old run reports `closed_summary_readable`, with final coverage `unavailable` and reason `legacy_format_has_no_artifact_bound_final_coverage`. It does not infer PASS from legacy `completed` lists or invent artifact binding/persistence confirmation.

Caller observations and persisted snapshots intentionally differ. `run/end` records what was known before its append; `result.json` records what was known before its write. Neither certifies its own successful persistence. Unconfirmed writes can leave readable bytes. Inspection reports both journal structure and any independently persisted writer observation, plus missing/invalid/readable summary status. Failures occurring after the last successful write cannot be reconstructed as if they had been recorded. Cleanup errors remain caller-observed if no later durable record exists; history is not rewritten.

## Changed files and preservation

Implementation changes: `end_harness/__init__.py`, `adapters.py`, `artifacts.py`, `checks.py`, `cli.py`, new `coverage.py`, `demo.py`, `encoding.py`, `events.py`, `providers.py`, and `runtime.py`; package version in `pyproject.toml`.

Tests: new `test_audit_boundaries.py`, `test_coverage_v011.py`, `test_finalization.py`, `test_loaded_engine.py`; the existing real-regression helper in `test_integration.py` now opts into the probe explicitly. Other original tests remain unchanged.

Documentation: updated README, architecture, integration gaps, and this report; added the v0.1 report archive and `AUDIT_v0.1.1.md`. New outputs are under `output/demo-v011` and `output/validation-v011`; the old directories are preserved. The initial 60-file Harness manifest and changed-file list are retained in the new validation directory. Before publication, overwritten destinations were checked against the baseline hashes to avoid overwriting unrelated edits.

Verified unchanged: **all 32 historical output files**, plus the byte-identical original report archive.

## External reference integrity

The existing manifest tool was used before and after testing:

```powershell
& $HarnessPython -B tools/reference_manifest.py 'E:\The End Engine' output/validation-v011/engine-after.json
& $HarnessPython -B tools/reference_manifest.py 'E:\The End\The End Harness\END-Harness-Research\deepseek-harness' output/validation-v011/deepseek-after.json
```

Before/after manifests match exactly:

| Reference | File count | Manifest SHA-256 |
|---|---:|---|
| END Engine, including existing tests/configuration/historical artifacts | 148 | `a397aeeb20d862da17e5fbb71e9e1a5a1e255a95bbe252de45da72b42c3963a3` |
| DeepSeek reference, excluding Git metadata | 13,850 | `12d53d46bab6250a2cd4576936652bbebe81449df34a200747493f43baf3f7d2` |

Engine remains version 0.3.0 with no Git repository. Controlled runtime source fingerprint remains `11895bb98ac917622ac726dcced72f7e433ff10d503ba34e08a0c15ff835b4b9`.

DeepSeek HEAD remains `477b4f420553e8a52c2fbccc464d7561b239c443`, and `git status --short` is empty. No reference code was modified, installed, built, copied into Harness, or reloaded to bypass provenance checks.

## Remaining limits

No requested finding was deferred. Existing deliberate limits remain: END lacks a required-check manifest and can accept despite missing Harness evidence; resource exceptions are still Engine `EXTERNAL_BLOCKER`; cognitive imports are post-run; synchronous deadlines cannot cancel arbitrary blocking work; opaque provider work cannot be fully metered; token estimates do not establish a ceiling; hashes are not an atomic/security guarantee; interrupted closure cannot resume END or invent unrecorded outcomes. These are documented without adding another quality gate or speculative infrastructure.
