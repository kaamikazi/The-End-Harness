# END Harness v0.2 implementation report

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Finalized 2026-09-29. Project: **`E:\The End Harness`**. Package version: **0.2.0**. The offline implementation is complete and verified. The real local-model pilot stopped at its preregistered development preflight; no held-out performance comparison was completed.

The earlier report is preserved as `IMPLEMENTATION_REPORT_v0.1.1.md`, alongside the existing v0.1 report and v0.1.1 audit. All 69 historical output files were hash-verified unchanged.

## Implemented

- A standard-library Ollama transport using explicit loopback endpoint/model configuration, documented discovery/capability APIs and ordinary/structured generation. It preserves complete requests, raw HTTP bytes/model output, parse/schema/finish status, installed model digest/settings, elapsed time and available usage. It has finite timeouts, a response-size bound, no hidden retries, no JSON repair, no automatic model pull, no proxies/redirects, and no remote endpoint support.
- A versioned deterministic task contract and frozen six-development/twelve-held-out suite across dependency/resource scheduling and structured-record filtering/grouping/ordering. All requirements and schemas are disclosed. Duplicate instances across splits are rejected.
- A small trusted `CheckBinding` generalization of the existing ToolVerifier. The deployment binding remains the default. Required checks and scopes come from task configuration, model-authored requests remain inert unless mapped, and receipts bind candidate/tested hashes, task/input hashes, checker version and configuration hash.
- SINGLE, SIMPLE_REVISION and real END conditions with identical visible task information and initial requests. Both iterative conditions share the same configured request/check/deadline limits. A parent budget caps all runs and every END role request. Native Engine selection/rollback remains authoritative; ordinary END experiments request no post-acceptance probe.
- Independent post-submission final evaluation and retrospective initial evaluation. Neither supplies feedback to running models or judges. Success is schema-valid output plus all required final checks on the submitted artifact, not a subjective judgment or Engine acceptance label.
- Durable experiment manifests/journals, per-run outputs, candidate-bound development/final receipts, all task-level outcomes, paired comparisons, token/usage coverage and failure metrics, JSON/CSV aggregates and readable reports. Live, synthetic and replay origins are distinct; summaries are read-only historical analysis, not new inference.
- CLI commands for discovery, preflight, development tasks, the full pilot, read-only summarization, and existing demos/inspection/tests.

No Engine source or quality gate was changed. There is no training export, model promotion, generated-code execution, general-purpose tool agent, UI, plugin framework, dependency installation or paid service.

## Inspected baseline

Read the current runtime modules, relevant tests, README, architecture, integration gaps and v0.1.1 audit before editing. The project had no Git working tree and no applicable Harness `AGENTS.md`. Files were staged in the supplied writable workspace, then copied into the requested project only after destination hashes matched the initial manifest.

Actual pre-change validation against the local Engine: **88 Harness tests passed in 16.573 seconds**. Engine version was confirmed as **0.3.0**, with the same controlled source fingerprint as before. No reported test count was assumed.

The official Ollama documentation was consulted before implementation: [API introduction](https://docs.ollama.com/api/introduction), [model inventory](https://docs.ollama.com/api/tags), [model details](https://docs.ollama.com/api-reference/show-model-details), [generation](https://docs.ollama.com/api/generate), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs), and [generation parameters](https://docs.ollama.com/modelfile). The adapter uses GET `/api/tags`, POST `/api/show`, and POST `/api/generate`; it sends `stream=false`, explicit generation options and schema `format`, then validates responses itself.

## Actual verification

Python executable used:

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'E:\The End Harness'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
$env:PYTHONPATH = 'E:\The End Engine'
& $HarnessPython -B -m unittest discover -s 'E:\The End Engine\tests' -v
```

| Check | Actual final result | Evidence |
|---|---|---|
| Complete Harness suite, including real Engine integration | **112 passed in 17.611 s** | `output/validation-v02/harness-tests.txt` |
| Unchanged Engine suite | **115 passed in 3.379 s** | `output/validation-v02/engine-tests.txt` |
| Original deployment CLI demo | Exit 0; C0 fails, C1 passes, C2 fails, native rollback selects C1 | `output/validation-v02/deployment-demo.json` |
| v0.1 run inspection | Exit 0; legacy evidence status remains conservative | `output/validation-v02/inspect-v01.json` |
| v0.1.1 run inspection | Exit 0; bound final-candidate coverage retained | `output/validation-v02/inspect-v011.json` |
| Read-only corrected pilot summary | Exit 0, no model calls | Pilot `aggregate_corrected_v2.json`, `summary_corrected_v2.json` |
| Historical/reference/source audit | All checks pass | `output/validation-v02/integrity-summary.json` |

The 24 new tests cover local fake-HTTP request/response translation, raw output and usage, malformed JSON/schema, response limits/incomplete generation, timeout/refusal/HTTP failures, local endpoint restrictions, no hidden retries, shared model/judge calls, frozen tasks and split duplicates, hand-verified reference checks, task/artifact/checker binding, hidden-information isolation, equal iterative caps, native rollback submission, accepted Engine verdict with missing final evidence, evaluator errors, origin/failure aggregation, preflight stopping, and corrected planned-versus-dispatched denominators. Existing 88 tests remain included. No real-model generation is made by the test suite.

Additional commands executed:

```powershell
& $HarnessPython -B -m end_harness discover-models
& $HarnessPython -B -m end_harness demo --engine-source 'E:\The End Engine' --output output/deployment-compat-v02
& $HarnessPython -B -m end_harness inspect output/demo/953efb95-5f0f-445c-a35b-a56ef637ec3a
& $HarnessPython -B -m end_harness inspect output/demo-v011/6ca43c52-50cb-476d-bb2b-66166ca0766d
```

The compatibility demo is explicitly SYNTHETIC. Its accepted C1 result is not real-model benchmark evidence.

## Local model and pilot outcome

Ollama was already running at `http://127.0.0.1:11434`. Installed models were `qwen2.5:1.5b`, `qwen3:4b`, and `qwen3:8b`. The pilot used the smallest installed completion model, **qwen2.5:1.5b**, Q4_K_M, about 986 MB; no model was downloaded or installed.

Installed digest: `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`.

Actual pilot command:

```powershell
& $HarnessPython -B -m end_harness pilot --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --output output/experiments-v02 --model-requests 14 --check-attempts 4 --run-seconds 60 --max-total-requests 522 --max-seconds 900 --timeout 25 --num-predict 1024 --num-ctx 8192 --seed 20260928 --temperature 0
```

Experiment ID: `78d73497-11b6-46da-bd2f-51881170ac14`.

The persisted plan bounded 54 condition runs over six development and twelve held-out tasks, at most 522 generation requests and 900 seconds at dispatch boundaries. The first development task across all three conditions was the protocol preflight. SINGLE had a one-request cap; SIMPLE_REVISION and END each had 14 requests, 4 development checks and a 60-second run deadline. Every request used the same model/settings. Final evaluation was separately bounded post-run measurement with no feedback or extra generation allowance.

Observed result: **BLOCKED / protocol_preflight_blocked** after three generation attempts and **67.487 seconds** of experiment journal time:

| Condition | Actual requests | Development preflight outcome |
|---|---:|---|
| SINGLE | 1 | 25-second transport timeout; no submitted artifact |
| SIMPLE_REVISION | 1 | 25-second transport timeout; no submitted artifact |
| END | 1 | Incomplete generation, `done_reason=length`, at 1,024 output tokens; Engine preserves `EXTERNAL_BLOCKER` |

No development or final reference checker executed. Six initial/final submission inspections recorded missing artifacts. There were zero successful submissions, but these failures are not checked incorrect answers. **All 36 held-out condition runs remained unrun; held-out success rates are unavailable.** The other 15 development condition runs also remained unrun. No budgets were enlarged, model swapped, or live calls repeated after the blocker.

Reported usage is partial: **461 input and 1,024 output tokens** from one request; the other two requests have unknown usage. There were zero retries. No assertion is made about total token consumption or immediate server-side cancellation after client timeouts.

Full observations, paths, limits and interpretation are in [PILOT_REPORT.md](PILOT_REPORT.md). This is a real local-model preflight failure record, not a completed comparative benchmark or evidence for/against END's task-performance benefit.

## Preserved methodology corrections

The actual pilot used `controlled-evaluation/1`. Offline review afterward found that two original aggregate labels conflated planned live-origin rows with dispatched runs, and missing submissions with evaluated incorrect outputs. Those derived count claims are invalidated and replaced by aggregate format 2. Original journal, manifest, outcome rows, aggregates and report remain unchanged; corrected summaries and `REPORTING_CORRECTION.json` are new sidecars.

The future protocol is **controlled-evaluation/1.1**, tested offline. It also forwards the same full development-feedback payload through END's evidence description that SIMPLE_REVISION receives directly; the original task binding only passed scope/Boolean status to END. No checker executed in the original pilot, so this did not affect an observed candidate or score. No held-out scores were observed and no task/prompt/seed/model/cap tuning occurred. No new real-model pilot was made after these corrections.

Original protocol and the changed Harness source files are archived with the experiment. Reconstructing the generation-time source manifest from those archives matches its recorded Harness hash:

`1ad9ac2dec1657f3e510bdaf200a5485b96cc617a413889141a01992a6d4fbeb`

The original experiment is explicitly unsuitable for performance comparisons. Corrections are historical reaggregation, not fresh model evidence. The resumed finalization followed a temporary automatic-approval usage-limit failure; that rejected command made no changes and was retried only after the user requested it.

## Files and artifacts

New runtime modules: `ollama.py`, `tasks.py`, `evaluation.py`, `experiment.py`. Existing `adapters.py`, `artifacts.py`, `budget.py`, `checks.py`, `coverage.py`, `providers.py`, `runtime.py`, `events.py`, `cli.py`, and package/version metadata were extended. New tests are `test_ollama.py` and `test_experiment.py`. The final audit helper is `tools/finalize_v02.py`.

Documentation: updated README/architecture, new `EXPERIMENT_PROTOCOL.md`, this report, archived `IMPLEMENTATION_REPORT_v0.1.1.md`, and `PILOT_REPORT.md`. Prior reports/audit remain intact. The separate Engine integration gaps remain applicable; no second internal gate was added.

Artifacts are under `output/experiments-v02/<experiment-id>`, `output/validation-v02`, and `output/deployment-compat-v02`. They include discovery metadata, immutable experiment manifest and source identity, full task hashes/configuration, runtime/evaluation journals, raw responses/failures, per-task outcomes, JSON/CSV results, original and corrected reports, and integrity proofs.

## Integrity and remaining limitations

The existing per-file manifest approach verified:

- **148 Engine files unchanged**, including tests/configuration/historical artifacts. Manifest SHA-256: `a397aeeb20d862da17e5fbb71e9e1a5a1e255a95bbe252de45da72b42c3963a3`.
- **13,850 DeepSeek reference files unchanged**, excluding Git metadata. Manifest SHA-256: `12d53d46bab6250a2cd4576936652bbebe81449df34a200747493f43baf3f7d2`. Git status is clean; HEAD remains `477b4f420553e8a52c2fbccc464d7561b239c443`.
- **All 69 historical output files unchanged**, with both prior implementation reports and the v0.1.1 audit preserved.

Engine remains 0.3.0 with controlled source fingerprint `11895bb98ac917622ac726dcced72f7e433ff10d503ba34e08a0c15ff835b4b9`. Tests create outputs outside Engine source and disable bytecode writes.

The comparison is request-budget-matched, not equal-compute. Same-model judging is correlated. END still may accept despite missing required evidence; external task evaluation is separate and never changes its selection/gate. Templates and small samples limit generalization. Synchronous deadlines do not forcibly cancel arbitrary blocking work; transport operations have finite bounds and total-read checks. Failed request usage can be unknown. Model tags/filesystem hashes do not provide an atomic or adversarial identity guarantee. Full Engine crash resume remains out of scope. The bounded real pilot did not pass protocol preflight, so no intelligence or task-performance improvement claim is supported.
