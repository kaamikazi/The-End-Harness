# END Harness v0.1.1 correctness audit

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Completed 2026-09-28 against `E:\The End Harness` and the read-only local END Engine 0.3.0. This audit covers the requested runtime boundaries, not a security certification or a change to END's acceptance policy.

## Baseline and method

The original implementation and all runtime modules, tests, README, architecture, implementation report, and integration gaps were read before editing. No applicable Harness/Engine `AGENTS.md` and no Harness Git repository were present. Existing files were hashed before editing. A working copy was made in the already writable workspace, then changed files were copied back only after their destination hashes matched the initial manifest. Existing run artifacts were not regenerated, migrated, or overwritten. The exact original report is preserved as `IMPLEMENTATION_REPORT_v0.1.md`.

The actual baseline command was:

```powershell
& 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B 'E:\The End Harness\tools\run_tests.py' --engine-source 'E:\The End Engine'
```

Observed result: **51 tests passed in 2.715 seconds**. The former report's Harness count was reproducible; it was not assumed. The final suite contains **88 tests**, including all 51 original cases and 37 new regressions. The original regression integration helper now explicitly opts into post-acceptance probing to preserve its intended test scenario.

## Confirmed findings and repairs

### F1: finalization could escape without a structured result

Trigger: failure during `run/end`, `result.json`, or journal cleanup. v0.1 set `complete=True` after import and performed these writes outside its main handler. This conflated successful import with closed history, could lose an otherwise available Engine result to an unstructured exception, and allowed a cleanup exception to mask the primary failure.

Repair: [runtime.py](end_harness/runtime.py), `RunResult`, `persisted_payload`, and `run_task` (lines 31, 58, 69) now distinguish execution, snapshot, import, closure, summary, and cleanup. Each final write has guarded handling; all ordinary failures return a partial `RunResult`. The ordered failure list preserves an earlier budget/runtime cause. Poisoned journals receive no further writes. Cleanup is attempted through `finally`; cancellation still propagates without being replaced by cleanup failure. If END's own ledger raises after a native final result exists, its public trajectory supplies that result with a labelled source.

The caller observes successful writes only after they return. `run/end` does not certify its own persistence. `result.json` does not certify its own write or future cleanup. Immutable records are never rewritten after later failures. [events.py](end_harness/events.py), `inspect_run` (line 68), independently reports readable journal closure, summary presence/validity, and any prior writer observation. It can reconstruct a native Engine result from a matching durable/readable snapshot when final records are absent, without fabricating the missing failure records.

Regression evidence: [test_finalization.py](tests/test_finalization.py), 13 tests exercising actual surviving files: end write failure, end fsync failure with surviving bytes, missing/partial summary after end, snapshot failure, interrupted import, poisoned import checkpoint, combined summary/cleanup failure, earlier budget cause, no self-certification, cancellation cleanup, both final writes failing, and Engine-ledger failure.

### F2: invalid Unicode rejection could raise the same encoding error twice

Trigger: an actual unpaired surrogate in `candidate.content`. v0.1's rejection handler caught `UnicodeError`, then attempted the same UTF-8 encoding again to compute a hash. Adjacent exception strings could also contain surrogates and poison diagnostic serialization.

Repair: [artifacts.py](end_harness/artifacts.py), `original_identity`, returns a null candidate hash with an explicit reason when UTF-8 bytes cannot exist. [adapters.py](end_harness/adapters.py), `HarnessToolVerifier.collect` (line 186), emits a structured rejection and uniform coverage. Any diagnostic representation is labelled `python_ascii_repr`, never substituted as artifact content or hashed as the original. [encoding.py](end_harness/encoding.py), `diagnostic` (line 34), is shared by provider, checker, opaque-judge, runtime, and CLI error reporting.

Regression evidence: actual `chr(0xd800)` input, ordinary malformed JSON with a real original hash, valid Bengali Unicode JSON, provider and checker exceptions containing a surrogate, and cleanup exceptions containing a surrogate. No rejected artifact enters positive evidence.

### F3: coverage did not identify the returned candidate or distinguish outcomes

Trigger: native rollback, absent required checks, repeated checking, malformed input, or a completed FAIL. v0.1 returned only a history of required/completed/missing IDs. A consumer could incorrectly use the last candidate or treat completed as passed. Invalid JSON had a different record shape, and model requests were merged into required checks.

Repair: [coverage.py](end_harness/coverage.py), `coverage_record` and `final_coverage` (lines 13, 33), plus `HarnessToolVerifier.collect`. All records include run identity, paired trajectory/candidate identity, original hash, exact tested artifact metadata, required versus optional checks, status/verdict/receipt references, completed/passed/failed/errored/unknown/missing lists, and unsupported requests. Final coverage resolves the real Engine result/public trajectory and verifies returned-content consistency. It never substitutes `latest_candidate_id` or combines evidence across bindings.

Repeated checks select the latest recorded collection for the exact binding, including incomplete/error/unknown collections. Earlier passes are not merged. History and receipt references remain, with `repeat_count` and `conflicting_checks`. Failed receipt validation cannot enter `passed`. This is evidence reporting only; the original Engine verdict remains unchanged.

Regression evidence: [test_coverage_v011.py](tests/test_coverage_v011.py), 12 tests covering native C2 → C1 selection, different-candidate/run/artifact isolation, completed FAIL, accepted-but-missing required checks, uniform invalid/valid/unavailable shapes, no final identity, optional requests, conflicting repeats, later unknown outcomes, and failed receipt translation.

### F4: generic runtime requested a regression probe by default

Trigger: an ordinary `RunConfig` implicitly used `post_acceptance_cycles=1`. This requested extra work after acceptance outside an explicitly chosen regression demo.

Repair: default changed to zero in [runtime.py](end_harness/runtime.py), `RunConfig` (line 16); [demo.py](end_harness/demo.py), `run_demo`, explicitly sets one for its labelled synthetic regression probe. END's defaults and candidate selection are unchanged.

Regression evidence: normal defaults stop at C1 with 13 model requests/two checks; the explicit probe reaches C2, rejects it, and returns C1 with 21 model requests/three checks.

### F5: current disk hashes could misdescribe already-loaded Engine modules

Trigger: Engine source changes at the same path after Python has cached its modules, or Engine was imported before Harness-controlled loading. v0.1 rehashed current disk files and attached that identity to potentially older loaded code.

Repair: [adapters.py](end_harness/adapters.py), `_source_identity` and `load_engine` (lines 29, 40). A controlled initial load compares before/after manifests and pins path/version/manifest/fingerprint. Reuse checks the pinned identity and returns a defensive copy. Same-path drift invalidates the process, even if files are restored. Different source and uncontrolled prior imports are rejected. A fresh process is required; no Engine modules are reloaded/deleted to bypass the check.

Regression evidence: [test_loaded_engine.py](tests/test_loaded_engine.py), six fresh-interpreter tests over disposable Engine copies: stable reuse, defensive copy, same-path drift before run creation/dispatch, another source, uncontrolled import, drift during initial import, and sticky invalidation after restoration (some assertions share a case). The real dependency was never edited for these tests.

## Additional substantiated boundary defects

| Finding | Trigger / incorrect behavior / impact | Minimal repair | Regression |
|---|---|---|---|
| Opaque judge post-checkpoint deadline | Deadline expires after durable `judge/call`; old wrapper raised without a result even though it knew dispatch never occurred, leaving unnecessary unknown history | Emit linked `NOT_DISPATCHED` without invoking the judge | `test_opaque_judge_deadline_after_checkpoint_records_not_dispatched` |
| Validator mutation before dispatch | A trusted input validator mutates data/configuration; the checker executes changed data. Old post-check hashing rejected positive evidence afterward, but did not prevent the wrong input from reaching checker code | Rehash after validation and reject before charging/dispatch | `test_validator_mutation_is_rejected_before_checker_execution` |
| Receipt-file persistence failure did not poison shared writer | Catch a receipt write error, then reuse the shared provider wrapper; the journal still allowed another dispatch despite failed receipt persistence | Poison the shared journal on receipt write failure; artifact persistence failure also blocks subsequent work | `test_receipt_persistence_failure_blocks_later_provider_dispatch` |
| Unsafe error-message serialization | Provider/checker exception contains an unpaired surrogate; diagnostic serialization itself fails | Labelled lossless ASCII diagnostic representation | Provider/checker surrogate tests in `test_audit_boundaries.py` |

All additional findings have concrete regression triggers. Failed receipt translation was also checked while implementing the new coverage summary so a nominal checker PASS cannot bypass receipt validation in reporting.

## Audit paths retained without speculative changes

- [providers.py](end_harness/providers.py) `_request` and `for_run`, [budget.py](end_harness/budget.py), and model-judge wrappers: retries already reserve a fresh attempt, share the run budget, and remain explicitly classified and bounded. Model-backed judge cloning already preserves one request-level count. Existing tests pass; no second accounting layer was added.
- Deadline checks before and after checkpoints and poisoned-journal dispatch prevention were already present for model/check boundaries. They were retained; the opaque-judge reporting omission above was repaired.
- [artifacts.py](end_harness/artifacts.py), [checks.py](end_harness/checks.py) `validate_receipt`, and [encoding.py](end_harness/encoding.py): strict parsing, immutable writes, stored-hash checks, issued-receipt/candidate/configuration binding, and rejection of stale evidence were already implemented. No replacement artifact system was introduced.
- [events.py](end_harness/events.py): middle corruption detection, torn-tail preservation, linked results, deterministic recovery sidecars, and no automatic re-execution already worked. Existing recovery behavior was retained while inspection gained explicit persistence distinctions.
- Opaque judge internals and hidden transport retries remain unobservable by contract. Their limitation is explicit; no unsupported claim of full underlying request coverage is made.

All five requested findings were confirmed. None was rejected as inaccurate. No additional speculative concern was promoted to a defect. Unresolved practical limits are concurrent/malicious filesystem changes, arbitrary blocking synchronous code, opaque internal work, and the separate Engine interfaces described below; they were deliberately not expanded into infrastructure projects.

## Commands and observed verification

Run from `E:\The End Harness`:

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
$env:PYTHONPATH = 'E:\The End Engine'
& $HarnessPython -B -m unittest discover -s 'E:\The End Engine\tests' -v
& $HarnessPython -B -m end_harness demo --engine-source 'E:\The End Engine' --output output/demo-v011
& $HarnessPython -B -m end_harness inspect 'output/demo-v011/6ca43c52-50cb-476d-bb2b-66166ca0766d'
& $HarnessPython -B -m end_harness inspect 'output/demo/953efb95-5f0f-445c-a35b-a56ef637ec3a'
& $HarnessPython -B -m end_harness close-interrupted 'output/demo-v011/80d74419-0620-4a9b-80f1-a69bcd0c994e'
```

- Harness: **88 passed in 15.382 seconds**, including real Engine integration and all new regressions. `output/validation-v011/harness-tests.txt`.
- Unchanged Engine: **115 passed in 6.001 seconds**. `output/validation-v011/engine-tests.txt`.
- Demo: exit 0, C0 FAIL → C1 PASS → C2 FAIL → native rollback to C1, Engine `ACCEPTED_VERIFIED`. Final coverage selects C1's `deployment.safety` PASS with no missing required checks. Latest candidate remains C2 and its failure stays in history.
- Budget demonstration: run `d2abb104-7686-449e-96ae-de8b52cc0288`, Harness `model_attempts_exhausted`, original Engine `EXTERNAL_BLOCKER`, three charged model attempts.
- Old/new CLI inspection: both exit 0. Old coverage is explicitly `unavailable` with reason `legacy_format_has_no_artifact_bound_final_coverage`; original history remains visible. New coverage is artifact-bound to C1.
- Interrupted inspection/repeated closure: no automatic work; unmatched call remains unknown, torn tail remains intact, repeated closure files and original journal remain unchanged.

Demo model/judge responses remain **SYNTHETIC**. The trusted bounded transition checker actually executes. These results do not measure intelligence, judge accuracy, or production deployment safety.

## Compatibility and remaining limits

Package version is 0.1.1. Result/coverage payload schemas are 1.1; event envelope, artifact, receipt, and recovery formats stay at their existing versions. Historical files remain untouched. Inspection does not reinterpret legacy completion flags as passed checks, artifact binding, or successful summary persistence.

There is no new quality gate, training eligibility/export, generated-code execution, live API use, paid dependency, UI, plugin framework, or full crash resume. END may still accept despite a missing required check; that mismatch remains explicit in final coverage and `ENGINE_INTEGRATION_GAPS.md`. Resource exceptions still map to END `EXTERNAL_BLOCKER`. Full cognitive imports remain post-run. Deadlines cannot interrupt arbitrary blocking calls, and no hard token ceiling is claimed. Hashes and ordinary Python import cannot provide an atomic or adversarial filesystem guarantee. Inspection reports what survived, not failures or fsync confirmations that were never persisted.

Reference integrity was checked with the existing per-file manifest tool. Engine 148 files and DeepSeek 13,850 non-Git files match their pre-patch manifests; historical v0.1 artifacts and the archived report are also hash-checked. Detailed hashes and artifact locations are in `IMPLEMENTATION_REPORT.md` and `output/validation-v011/`.
