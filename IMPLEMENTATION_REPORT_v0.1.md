# END Harness v0.1 implementation report

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Completed and verified on 2026-09-27. Final project: **`E:\The End Harness`**.

## Delivered behavior

Implemented the complete offline path: task → Harness run → real local END Engine with wrapped providers → candidate-bound trusted JSON checks → END's existing quality gate and rollback → final result and inspectable runtime journal.

The implementation uses Python's standard library at runtime, synchronous execution, no network calls, and no paid services. The Engine's cognitive controller and quality gate are unchanged. No DeepSeek code was copied, built, installed, or forked.

Before implementation, the requested new project directory did not exist. Work was staged in the supplied workspace `E:\The End\The End Harness`, preserving its existing research directory, then copied to the exact requested project location and tested there. The architecture analysis and DeepSeek checkout were actually found under `E:\The End\The End Harness\END-Harness-Research`, rather than the older paths in the brief. No applicable Harness or Engine `AGENTS.md` was present; the reference repository guidance and relevant checkpoint/recovery sources were read before implementation. Neither Harness nor Engine had an existing Git working tree to preserve.

## Actual validation commands and results

Python executable used:

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
```

Its reported version was **Python 3.12.14**.

Final-location Harness tests:

```powershell
Set-Location 'E:\The End Harness'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
```

**Result: 51 tests passed in 2.938 seconds.** Captured output: `output/validation/harness-tests.txt`. The suite uses the real external Engine for its integration tests, including an actual subprocess exit during provider dispatch. Isolated boundary tests use small fixtures and fault injection; the integration Engine is not replaced with a fake.

Unchanged Engine tests, run from the Harness staging workspace with temporary outputs outside Engine source:

```powershell
$env:PYTHONPATH = 'E:\The End Engine'
& $HarnessPython -B -m unittest discover -s 'E:\The End Engine\tests' -v
```

**Result: 115 tests passed in 3.339 seconds.** Captured output: `output/validation/engine-tests.txt`. Existing Engine tests were neither changed nor weakened.

Final-location offline demo:

```powershell
& $HarnessPython -B -m end_harness demo --engine-source 'E:\The End Engine' --output output/demo
```

**Result: exit 0.** Normal run `953efb95-5f0f-445c-a35b-a56ef637ec3a`; Engine trajectory `adc2f2a1-9c8b-4284-8b2a-af2207446f25`. C0 failed, C1 passed, C2 failed after removing the healthy-replica guard. END recorded rollback C2 → C1 and returned C1 with `ACCEPTED_VERIFIED`, while `latest_candidate_id` remained C2. All candidates, completed receipts, original/canonical artifacts, judgments, gate decisions, and rollback history are retained.

The normal run charged **21 model attempts and 3 check attempts**. All 21 model token usages are explicitly unknown, reported/estimated token totals are null, and no reservations remain pending. Full request counting matches END's 21 recorded underlying model calls, with no extra charge at `JudgeProvider.evaluate`.

Budget-exhaustion run: `949adf14-0052-47be-b089-b27413226336`. After three model requests, Harness `model_attempts_exhausted` was preserved separately from END `EXTERNAL_BLOCKER` / `BLOCKED` / `INCOMPLETE`.

Interrupted journal fixture: `44458d20-b4ba-4c9c-a3b4-15471e4323d5`. Inspection retained two complete events and a 33-byte torn tail, marked its unmatched call `OUTCOME_UNKNOWN`, and reported unavailable Engine cognitive state. This demo fixture is explicitly manufactured; the separate subprocess integration test exercises a real process exit.

CLI inspection and repeat closure:

```powershell
& $HarnessPython -B -m end_harness inspect 'output/demo/953efb95-5f0f-445c-a35b-a56ef637ec3a'
& $HarnessPython -B -m end_harness close-interrupted 'output/demo/44458d20-b4ba-4c9c-a3b4-15471e4323d5'
```

**Both exited 0.** Results saved as `output/validation/inspect-completed.json` and `inspect-interrupted.json`. Repeat closure preserved the existing original journal and recovery annotation without re-execution or duplicate records. The complete demo console response is `output/validation/demo-console.json`; the full combined demo result is in `output/demo/demo-953efb95-5f0f-445c-a35b-a56ef637ec3a.json`.

## Test and evidence coverage

| Invariant | Executed verification |
|---|---|
| Shared request budget, generator/verifier/judges/adversary, no double count | Boundary tests across judge roles plus real trajectory-call count |
| Run-local provider clones retain wrappers and accounting | Independent clones consume the same budget |
| Retry charging and bounded exhaustion | Transient failure then success/exhaustion; retry linkage checked |
| Validation/journal/check failures are not automatically retried | Injected errors, malformed responses, result checkpoint failure |
| Usage provenance | Unknown, invalid, explicit reported zero, reported failure usage, separate estimates |
| Monotonic deadline | Before dispatch, after slow checkpoint, and real Engine stop translation |
| Journal fail-closed behavior | Provider/check checkpoint failures block actual invocation |
| Sequence/call linkage and recovery | UTC/sequence validation, unmatched calls, corrupted middle/final records, torn tails, atomic recovery retry |
| Artifact and receipt identity | Original/tested hash distinction, disk tampering, cross-candidate/trajectory/run rejection |
| Trusted input/output validation | Duplicate keys, nonfinite/overflowed numbers, wrong schemas, malformed checker output, mutation detection |
| Scope enforcement | Unknown checks, arbitrary claim IDs, unsupported model-authored commands/properties |
| Error/timeout/unknown versus verdict | No positive or negative evidence fabricated from incomplete execution |
| No cross-candidate result cache | Repeated checks each execute and charge an attempt |
| Real Engine lifecycle | C0/C1/C2 retention, best/latest distinction, native rollback, post-run import provenance |
| Known Engine limitations | Missing required evidence still allows acceptance; Harness exposes coverage without overriding gate |
| Actual process interruption | Real Engine child process exits at provider boundary; durable intent survives, full cognitive trajectory does not |

The deployment checker executes bounded transitions, records counterexamples, and binds results to the exact inert JSON. It does not read an `expected_answer` or return preassigned candidate scores. Model/judge outputs and pairwise preferences are prominently labelled synthetic fixtures. Their numerical scores are not experimental evidence of intelligence or judge quality.

## Created files

No existing Engine/reference file was modified. New Harness files are:

- `pyproject.toml`, `.gitignore`.
- `end_harness/__init__.py`, `__main__.py`, `encoding.py`, `events.py`, `budget.py`, `providers.py`, `artifacts.py`, `checks.py`, `adapters.py`, `runtime.py`, `demo.py`, `cli.py`.
- `end_harness/fixtures/faulty.json`, `improved.json`, `regressed.json`.
- `tests/support.py`, `test_boundaries.py`, `test_journal.py`, `test_checks.py`, `test_integration.py`.
- `tools/run_tests.py`, `tools/reference_manifest.py`.
- `README.md`, `END_HARNESS_ARCHITECTURE.md`, `ENGINE_INTEGRATION_GAPS.md`, `IMPLEMENTATION_REPORT.md`.
- Example run artifacts under `output/demo/`; test logs, CLI inspection outputs, and integrity manifests under `output/validation/`.

## Reference integrity

Engine version: **0.3.0**. No Engine Git repository exists. Runtime source fingerprint (canonical per-file hash manifest of `end_engine/**/*.py` and `pyproject.toml`):

`11895bb98ac917622ac726dcced72f7e433ff10d503ba34e08a0c15ff835b4b9`

Read-only whole-directory manifests were generated before and after execution with:

```powershell
& $HarnessPython -B tools/reference_manifest.py 'E:\The End Engine' output/validation/engine-after.json
& $HarnessPython -B tools/reference_manifest.py 'E:\The End\The End Harness\END-Harness-Research\deepseek-harness' output/validation/deepseek-after.json
```

The matching `*-before.json` manifests are also included. Engine **148 files**, including historical artifacts and existing bytecode, matched byte-for-byte before/after. Whole-manifest SHA-256:

`a397aeeb20d862da17e5fbb71e9e1a5a1e255a95bbe252de45da72b42c3963a3`

DeepSeek **13,850 files** excluding Git metadata matched before/after. Whole-manifest SHA-256:

`12d53d46bab6250a2cd4576936652bbebe81449df34a200747493f43baf3f7d2`

Reference HEAD remained `477b4f420553e8a52c2fbccc464d7561b239c443`. `git status --short` was empty on inspection and final verification. Git's ownership check was handled with a per-command `-c safe.directory=...` override, without changing global configuration.

## Material limits and remaining gaps

- Synthetic fixtures validate runtime control flow and bounded check execution, not improved intelligence, judge accuracy, or production safety.
- Deadline enforcement occurs at synchronous dispatch boundaries; arbitrary blocking work cannot be interrupted. There is no hard token ceiling.
- Opaque judges and hidden provider-internal retries/fan-out cannot have their underlying requests fully metered. The demo uses visible model-backed transports.
- END can accept despite missing required checks. Required/completed/missing coverage is exposed separately, and the smallest proposed Engine change is documented in `ENGINE_INTEGRATION_GAPS.md`.
- Resource exceptions remain END `EXTERNAL_BLOCKER`; Harness stop causes are distinct.
- Full cognitive history is imported after Engine return. Interrupted-run closure cannot restore Engine state or resume work.
- Journal durability relies on filesystem fsync guarantees. Single-writer operation and stopped-writer recovery are required. Hashes are integrity checks, not signatures or adversarial storage protection.
- Trusted checks inspect inert JSON only. There is no untrusted-code execution, shell executor, security sandbox, external-effect rollback, UI, plugin framework, training, model promotion, multi-agent runtime, or full crash-resume engine.

All supported v0.1 work is implemented and exercised with the real local Engine. Remaining Engine-interface gaps are explicit rather than hidden behind a substituted integration or a second quality gate.
