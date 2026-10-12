# END Harness v0.2

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

A synchronous, standard-library Python runtime around the **real, separately maintained END Engine**. The Harness owns request/check accounting, durable call records, immutable JSON artifacts, execution receipts, and run lifecycle. END owns cognition, judgments, the quality gate, candidate selection, and rollback.

v0.2 adds an explicit local Ollama adapter and a frozen SINGLE / SIMPLE_REVISION / END evaluation runner. Task success comes from post-run deterministic reference checks, separately from END's verdict. See [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md) for the frozen tasks, budgets and limitations.

An optional **Antigravity CLI (`agy`) provider** can run a bounded integration smoke with a Google AI plan's account-authenticated headless route. It is not eligible for the controlled benchmark; see [below](#optional-antigravity-provider-integration-smoke-only) and [ANTIGRAVITY_INTEGRATION_REPORT.md](ANTIGRAVITY_INTEGRATION_REPORT.md).

**Current offline compatibility check (2026-10-12): passes against the selected Engine 0.3.5.2 checkout—157 tests, 0 failures, 0 errors, 0 skips after focused PR review.** See [COMPATIBILITY.md](COMPATIBILITY.md) for the fingerprint, reproduced 149-test failing baseline, repairs, and support limits. Historical Antigravity smokes used Engine 0.3.0 and 0.3.2; the repeat used 3 probes plus 13 END provider invocations, accepted provisionally, and passed development/reference checks. See [ANTIGRAVITY_INTEGRATION_REPORT.md](ANTIGRAVITY_INTEGRATION_REPORT.md) for both records and their limitations. The Qwen pilot stopped at preflight with no held-out evaluation. These records demonstrate no task-performance improvement.

The original offline deployment demo remains **SYNTHETIC**. Its trusted checker enumerates transitions in an abstract model. Fixture runs and replayed responses are never counted as live-model evidence.

## Local-model evaluation commands

No model download, installation, credentials, paid services, or remote endpoints are used. Discover an already-running local Ollama service and choose an installed completion model explicitly:

```powershell
Set-Location 'E:\The End Harness'
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $HarnessPython -B -m end_harness discover-models
& $HarnessPython -B -m end_harness preflight --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --max-total-requests 29 --max-seconds 180
& $HarnessPython -B -m end_harness develop --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --max-total-requests 174 --max-seconds 360
& $HarnessPython -B -m end_harness pilot --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --output output/experiments-v02
& $HarnessPython -B -m end_harness summarize 'output/experiments-v02/<experiment-id>'
```

The model name above is an installed model on this machine, not a library default. Replace it with a name returned by discovery. The pilot includes a development preflight; separate preflight/develop commands are optional independent runs. Discovery and summarization make no generation calls. A missing service/model is an access blocker, never a reason to substitute mocks or download weights.

Each experiment writes a preregistered manifest and journal before generation, then per-run artifacts, raw transport observations, candidate-bound development/final receipts, task outcomes, `aggregate.json`, `aggregate.csv`, `results.csv`, and `REPORT.md`. Final diagnostics are never fed back into conditions. With defaults there are six development and twelve held-out tasks, 54 planned condition runs, at most 522 generation requests, and a 900-second dispatch deadline. Each iterative run has the same 14-request, 4-development-check, 60-second limits; SINGLE has one request. Post-run evaluation allows one check each for the initial and final submissions. The request timeout is 25 seconds; HTTP responses are limited to 1 MiB.

The adapter sends full prompt/context/schema using Ollama's documented `/api/generate` fields, validates structured responses, retains raw bytes/output and failure status, and never repairs malformed outputs or retries invisibly. Same-model judging is correlated. This is request-budget matching, not equal compute. Reported tokens and their coverage, all failures, and paired outcomes are retained; small shared-template tasks cannot establish broad intelligence gains.

## Optional Antigravity provider (integration smoke only)

The available local records include the first smoke and a successful repeat on 2026-09-30. Raw evidence is local only and excluded from the public repository. The repeat does not isolate an Engine-version effect; `benchmark_eligible=false` still applies. This publication task launched neither a smoke nor a benchmark.

`end_harness/antigravity.py` drives the documented `agy` headless route: `-p <prompt> --output-format json --json-schema <schema> --model <slug> --print-timeout <n>s --sandbox`, as an argument list with no shell. A documented stdin route (`--prompt-transport stdin-stream-json`) is available as an alternative. `--sandbox` is documented as "Run with terminal sandbox restrictions enabled"; the adapter cannot verify how the CLI enforces it. The adapter never passes `--dangerously-skip-permissions`, `--continue`/`-c`, `--conversation`, `--agent` or `--mode`. Each invocation gets a fresh, empty working directory outside the project, which is removed afterwards. API-key variables are stripped from the child process and CLI auto-update is disabled. Output is capped (1 MiB stdout, 256 KiB stderr) and each invocation has a time limit (90 s maximum, less when the dispatch deadline is closer). On Windows the process tree runs in a job object, so only processes this adapter started are terminated. Retained stdout/stderr is redacted for token patterns; hashes identify the original bytes. Responses are validated against END's schemas without repair. Failures are categorised separately: authentication, quota, timeout, process, incomplete generation, protocol, parse, schema, output-limit and session-isolation. The adapter makes no retries.

Before any `agy` process runs, the adapter checks prerequisites and fails closed if they are not met. `~/.gemini/antigravity-cli/settings.json` must leave `modelProvider` unset and contain no `permissions.allow` rules. `toolPermission` must be `request-review` or `strict`. There must be no `GEMINI.md`/`AGENTS.md`/`.agents` instruction sources.

**Credit overage (project policy).** Overage must be disabled on every documented surface. Two things must hold:

1. The CLI's `useG1Credits` must be effectively false. The Harness verifies this by reading `settings.json`:
   - An explicit `false` passes.
   - An absent key also passes. The CLI reference documents the default as `false`, and the settings page documents *sparse persistence* ("writing only values to disk that differ from their system defaults"). That is why `agy` 1.2.13 drops an explicit `false` when it saves.
   - An explicit `true`, a malformed value or a missing file blocks.
2. You must confirm that the Plans page's "AI Credit Overages" user setting is **Never**, via `--account-credit-overages never`. This is recorded as user confirmation, not machine verification. `unconfirmed` (the default) and `always` both block. The setting's location, its default and its precedence over `useG1Credits` are undocumented.

This check runs before any CLI process, again after the metadata commands, and before every prompt. Resolving it enables only the bounded smoke; benchmark use stays blocked. `antigravity-disable-credits` (backup first, other settings preserved) is still available, but it is unnecessary under sparse persistence.

The CLI's `--help` output must list every flag used. `--help` itself is not in the official flag table, so if it fails the installed flags cannot be verified and the check blocks. `--version` is also undocumented; it is recorded when available but never blocks. The requested model must appear in `agy models`.

**Accounting.** One budget unit is one `agy` process (a *provider invocation*), not one model request. `agy` is an agent runtime, so underlying model requests, hidden retries, internal loops and model fallback cannot be observed. Reported `usage` covers a whole invocation, and its aggregation scope is undocumented. `num_turns` is recorded only as a reported field. Only invocations are hard-bounded. For these reasons, together with the lack of documented per-run controls for browsing, subagents, plugins/MCP and model fallback, `run_experiment` refuses the Antigravity origin, so benchmark use stays blocked.

```powershell
Set-Location 'E:\The End Harness'
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$Agy = "$env:LOCALAPPDATA\agy\bin\agy.exe"   # documented Windows install directory; verify the file name after installing
& $HarnessPython -B -m end_harness antigravity-check --executable $Agy --model '<slug from agy models>' --list-models
& $HarnessPython -B -m end_harness antigravity-smoke --engine-source 'E:\The End Engine' --executable $Agy --model '<slug from agy models>'
```

The smoke writes its manifest to a fresh `output/antigravity-smoke/<id>/` directory before any CLI process runs. It then allows at most 3 protocol probes (candidate, judgment, verifier), then at most one END run on `development-scheduling-100`. That run gets at most 14 provider invocations and 4 development checks. The whole smoke is capped at 17 invocations and a 600 s dispatch deadline. These limits cannot be raised from the CLI. `--version`, `--help` and `agy models` are recorded separately as metadata commands. While it runs, the smoke prints progress to stderr (stage, invocation count and purpose, elapsed time, and the outcome or failure category), never prompts or responses; the JSON result stays on stdout. It journals `smoke/dispatch_budget` with the UTC deadline, and `smoke-result.json` records a `timing` block (dispatch span, deadline margin, finalization, longest invocation). Historical preparation notes and verified smoke status: [ANTIGRAVITY_INTEGRATION_REPORT.md](ANTIGRAVITY_INTEGRATION_REPORT.md).

## Run without installing packages

Requires Python 3.11+ and a separate local Engine source checkout. The selected Engine identity and actual test result for the 2026-10-12 offline repair are in [COMPATIBILITY.md](COMPATIBILITY.md); previous releases were checked against Engine 0.3.0 and 0.3.2. The integration test reads the expected Engine version from the selected checkout's `pyproject.toml` rather than pinning a release. There are no runtime third-party dependencies, downloads, or global installations. The synthetic demo and tests work offline; real experiments use only the explicitly selected local service. The Engine is not copied into this package or fetched from PyPI.

On this machine, from PowerShell:

```powershell
Set-Location 'E:\The End Harness'
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $HarnessPython -B -m end_harness demo --engine-source 'E:\The End Engine' --output output/demo
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
```

On another machine, substitute your Python executable and Engine path. `--engine-source` explicitly selects the dependency; library modules contain no machine-specific Engine path. Engine identity currently accepts three or four ASCII numeric version components; other release suffix/build formats are unsupported. Call `load_engine(source)` before importing Engine interfaces when using the Python API. The first controlled import compares before/after source manifests and pins its path, version, and fingerprint. Reuse checks that source against the pinned identity. A prior uncontrolled import, different source, or detected source drift requires a fresh process; modules are never reloaded to bypass the check. Bytecode writes are disabled. Hash comparisons are not atomic protection against concurrent or malicious filesystem changes.

The demo prints `run_directory`, `exhaustion_directory`, and `interrupted_directory`. Inspect those paths with:

```powershell
& $HarnessPython -B -m end_harness inspect 'output/demo/<run-id>'
& $HarnessPython -B -m end_harness inspect 'output/demo/<interrupted-run-id>'
& $HarnessPython -B -m end_harness close-interrupted 'output/demo/<interrupted-run-id>'
```

Replace `<run-id>` with an actual printed directory name. Inspection needs no Engine import. Close an interrupted run only after its writer has stopped. Closing is historical annotation, never execution or Engine resume. Repeating closure produces no duplicate records.

To independently run the unchanged Engine suite with outputs outside its source tree:

```powershell
$env:PYTHONPATH = 'E:\The End Engine'
& $HarnessPython -B -m unittest discover -s 'E:\The End Engine\tests' -v
```

That suite uses temporary output directories. `-B` prevents bytecode writes into the read-only reference. Historical checks reported 135 Engine tests on 0.3.2 and 115 on 0.3.0. The Engine suite was not run for the 2026-10-11 publication or the 2026-10-12 Harness repair; those counts are not a current Engine-test claim. Current Harness compatibility is reported separately in [COMPATIBILITY.md](COMPATIBILITY.md).

## What the demo shows

| Candidate | Actual check result | END behavior |
|---|---|---|
| C0: stop up to two replicas without a healthy-replica guard | FAIL; counterexample traces retained | Requests revision |
| C1: restrict stopping to preserve one healthy replica | PASS within enumerated bounds | Accepts verified within recorded scope |
| C2: remove that guard | FAIL; counterexample traces retained | Rejects severe regression and rolls back to C1 |

The demo explicitly sets the Engine's supported `post_acceptance_cycles=1` option for the regression probe. Generic `RunConfig` defaults to zero and returns after acceptance without requesting that extra work. The Harness does not assign the returned candidate. A synthetic fatal finding about C2 cites its actual failed, candidate-bound checker receipt and declared safety scope. END grounds that finding and performs native rollback; pairwise model comparison scores remain advisory. Candidate checks are independent executions over each candidate's data.

The normal fixture uses **21 underlying model requests and 3 check attempts**. Generator, basic verifier, primary judge, adversarial-test generation, adversarial judge, and pairwise comparisons all use the same budget. Every fixture response has unknown token usage; totals are not fabricated.

The second run exhausts a three-request budget and retains END's `EXTERNAL_BLOCKER` result alongside Harness `model_attempts_exhausted`. A third, explicitly manufactured journal fixture has an unfinished call and torn tail. The test suite additionally exits a real Engine subprocess during provider dispatch to verify surviving evidence.

## Inspectable run files

```text
<run-id>/
  events.jsonl                append-only, schema 1.0, fsync on each event
  artifacts/<sha>.candidate   original candidate UTF-8 bytes
  artifacts/<sha>.json        exact canonical JSON supplied to the checker
  receipts/<execution>.json   immutable execution receipts
  engine/<trajectory>.jsonl   END's own completed ledger
  trajectory.json            full completed END snapshot
  result.json                separate Engine result, Harness cause, budget, coverage
  recovery.json              optional historical closure; original journal unchanged
```

Each runtime event includes run ID, sequence, UTC timestamp, call/parent linkage, structured payload, and an Engine reference when actually available. Engine local IDs always travel with their trajectory ID. Model call IDs assigned inside END are not guessed. Completed Engine steps are imported with `provenance="post_run_import"`, retaining their original timestamps inside the payload.

`inspect` reports the original `engine_result`, `harness_stop_cause`, `final_candidate`, artifact-bound `final_candidate_coverage`, and the separate full `evidence_coverage` history. It also reports unfinished calls, snapshot/import availability, and summary-file status. `completed` means the readable journal ends with a valid `run/end` and has no open calls or torn tail. It does not prove that the writer observed a successful fsync, that `result.json` exists, or that the task was accepted. `persistence.writer_closure_observation` is separate. A failed checkpoint can leave readable end bytes; inspection does not reinterpret that as caller-confirmed persistence.

## v0.1.1 result and failure contract

After Engine provenance preflight, `run_task` returns a structured `RunResult` for ordinary execution and finalization failures. It retains an available Engine result and reports independent `engine_execution`, `trajectory_snapshot`, `trajectory_import`, `journal_closure`, `summary_persistence`, and `cleanup` observations. If END's own ledger fails after computing a result, the supported public trajectory can supply that native result; `engine_result_source` distinguishes `returned` from `public_trajectory.final_result`, without claiming Engine execution returned normally. `harness_stop_cause` is the first observed cause; `failures` retains later causes and safely escaped diagnostics. A budget stop therefore survives a later disk or cleanup error. Preflight provenance/configuration errors raise before dispatch; process cancellation such as `KeyboardInterrupt` propagates after cleanup is attempted.

The returned object has `status_view="caller_observed"`. Journal closure payloads use `before_journal_closure`, omit their own closure confirmation, and omit future summary/cleanup status. `result.json` uses `before_summary_write`; it can record the previously observed journal-closure result but does not certify its own successful write or subsequent cleanup. Failed final writes are reported to the caller even when no durable failure record can be written. No writes are attempted on a poisoned journal, and immutable history is never rewritten to match later caller observations. `RunResult.journal_complete` remains a compatibility accessor for confirmed closure, with corrected semantics.

CLI inspection reports `closed_summary_missing`, `closed_summary_invalid`, `closed_summary_readable`, or the corresponding `incomplete_...` state. It uses surviving records, validates a summary's run identity and agreement with journal evidence, and can recover an Engine result from a matching readable trajectory snapshot when final records are missing. It cannot infer the success of a summary's own fsync or reconstruct an unrecorded cleanup failure. A run with an absent summary is not automatically an interrupted Engine run.

Result snapshots and coverage records now have schema **1.1**. The event envelope, receipt, artifact, and recovery formats remain unchanged. Historical v0.1 files are preserved and remain inspectable. Old coverage lacks artifact identity and PASS/FAIL distinctions, so inspection retains it as history and explicitly marks final bound coverage unavailable; it does not upgrade old `completed` lists into passed evidence or old `journal_complete` flags into closure confirmation.

## Final-candidate evidence reporting

Coverage resolves END's public final-candidate identity and returned content, including native rollback. It binds one collection to Harness run ID, Engine trajectory/candidate IDs, original UTF-8 hash, and exact tested artifact metadata. C1's coverage is reported after C2 → C1 rollback, even though C2 was checked last. A different candidate, run, content, or artifact cannot fill missing final evidence.

All coverage records use the same fields: binding, status/reason, required and optional check lists, per-check outcomes/receipt references, completed/passed/failed/errored/unknown/missing lists, unsupported requests, and repeat information. Model-requested checks are optional unless independently configured as required. Completed FAIL is completed but never passed. `missing` lists required checks without a completed, validated receipt, including unknown/error/unexecuted outcomes. This reports evidence; it does not add an acceptance gate.

Repeated collections use the **latest recorded collection for the same candidate and artifact, without merging earlier passes**. This includes interrupted/unavailable collections; it does not imply successful execution. The full history and receipts remain, `repeat_count` counts matching collections, and `conflicting_checks` exposes changed outcomes. A later FAIL, ERROR, or UNKNOWN cannot be filled by an earlier PASS. If identity/evidence is unavailable, coverage says so explicitly.

Invalid Unicode is rejected without replacement. When original UTF-8 bytes do not exist, `candidate_hash` is null with an explicit reason. Diagnostic strings use labelled `python_ascii_repr`; they are not candidate artifacts or substitute hashes. Ordinary malformed JSON retains its actual original UTF-8 hash. Neither rejection produces positive evidence.

## Check scope and trust

`deployment.safety` version 1 accepts exactly one whole JSON object with schema version 1 and fields `max_unavailable`, `require_healthy_before_stop`, and `rollback_on_failure`. Duplicate keys, nonfinite numbers, invalid Unicode, extra fields, wrong types, code fences, and trailing documents are rejected. Nothing is extracted from prose or silently corrected.

The fixed checker explores 2–3 replicas, 1..N initially healthy replicas, three deployment rounds, stop transitions, and success/failure outcomes. It asserts at least one healthy replica at each observed transition. It checks safety in that abstract model only. It does not check liveness, real orchestrator behavior, concurrent failures, networking, real rollback correctness, or security. `rollback_on_failure` influences the enumerated recovery transition but is not independently certified as a production rollback mechanism.

Checks are explicitly registered trusted Python functions operating on inert JSON. Input/output contracts are validated. Completed FAIL is negative evidence; ERROR, TIMEOUT, missing, and unknown outcomes are not verdicts. No performance criterion is registered in v0.1, so a timeout never becomes a failed functional claim. Check execution is never automatically retried.

Only exact, trusted claim-text mappings receive support. Model-authored test descriptions are inert unless they match the registered scenario, property, and mapped target exactly. Unsupported requests remain recorded as unexecuted. There is no cross-candidate result cache, shell executor, generated-code execution, or security sandbox.

## Budgets and limitations

- Model/check attempt limits and the monotonic deadline are separate units. Attempts are conservatively charged at reservation; a journal failure may leave a charged, pending reservation without dispatch.
- Intent and its checkpoint precede every dispatch. The deadline is checked again after the checkpoint. Persistence failure poisons the journal and blocks later dispatch.
- Only `TransientProviderError` is retryable, up to `max_retries`. Each retry reserves another request in the same budget. Provider adapters must classify transient failures explicitly.
- Tokens are labelled reported, estimated, or unknown. The default wrappers do not estimate. Reported and estimated counters stay separate; absent usage is `null`, not measured zero. No hard token ceiling is claimed.
- Deadlines are checked at synchronous dispatch boundaries. They do not interrupt blocking Python, model transports, or trusted checks already executing.
- Exact `ModelJudgeProvider` transports are unwrapped and rewrapped at the underlying request boundary. Wrappers survive END's `for_run` cloning. Opaque judges report an explicit coverage limitation: only invocations are observed; hidden model requests and tokens cannot be bounded. Use model-backed judges for full request-budget coverage.
- END has no required-check manifest. Missing required checks can coexist with its acceptance decision. The Harness exposes missing coverage and the integration gap without inventing a second quality gate.
- Runtime evidence survives only to durable checkpoints. Full Engine state is unavailable after a process crash unless a completed snapshot was durably imported. Recovery does not replay work.
- This is a single-process, single-writer runtime. Recovery requires a stopped writer; concurrent closure is unsupported. Hashes detect accidental mismatch; they are not digital signatures or protection against an attacker rewriting the whole run directory.
- No execution workspace is created for checks. Candidate rollback changes END's internal authoritative candidate; it cannot undo external effects.

See [architecture](END_HARNESS_ARCHITECTURE.md), [integration gaps](ENGINE_INTEGRATION_GAPS.md), [v0.1.1 audit](AUDIT_v0.1.1.md), and [implementation report](IMPLEMENTATION_REPORT.md). The original report is preserved as [IMPLEMENTATION_REPORT_v0.1.md](IMPLEMENTATION_REPORT_v0.1.md).
