# END Harness offline compatibility — 2026-10-11

**Result: compatibility is not established for the selected Engine checkout.** The unchanged supported Harness runner executed **149 tests in 69.928 seconds**, with **7 failures and 9 errors**, exit code **1**. These are the actual results from this publication task, not the historical passing results from September.

## Selected Engine identity

| Field | Observed value |
|---|---|
| Explicit source checkout | `E:\The End Engine` |
| Version from that checkout | **0.3.5.2** |
| Harness-computed source fingerprint | `29c0bbce13559ea595d34d9c78d4812811bcade144deb6fdbd8a231c4da4fc82` |
| Fingerprint scope | `end_engine/**/*.py` plus `pyproject.toml`, using the existing Harness loader's canonical per-file manifest |
| Loader provenance | `harness_controlled_initial_load` |
| Before/after identity | Identical across this validation |

The actual executable was the specified bundled Python at `C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; the personal username is generalized for publication. Engine 0.3.2 is the repeat smoke's recorded identity, not the identity selected for this check.

## Command and execution environments

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location 'E:\The End Harness'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
```

The first attempt ran under the desktop sandbox and could not write temporary fixture files or connect to the local fake HTTP server. It reported 149 tests in 7.193 seconds, 16 failures and 260 errors (including cleanup errors). That attempt is retained as infrastructure failure evidence; it does not establish Engine compatibility.

The exact supported runner was then retried with host permissions, bytecode still disabled, and no changes to source, fixtures, policies, budgets, or assertions. The host attempt ran in 69.928 seconds and still failed: **7 failures, 9 errors**. Its result is the compatibility result reported here. There were no live model calls, live CLI readiness checks, new live smoke runs, live benchmarks, or package installations. Antigravity subprocesses in these tests use the explicitly SYNTHETIC `tests/synthetic_agy.py`; Ollama HTTP tests use a local fake server.

The Engine suite was not run during this task. Historical counts of 115 Engine tests on 0.3.0 and 135 on 0.3.2 are not current test claims.

## Observed compatibility issues

Read-only source inspection found a concrete response-field mismatch: the selected Engine's `ModelResponse` now includes an optional `answer_content` field. Both existing Harness adapters create an `ObservedResponse` subclass using four positional arguments: `ObservedResponse(content, usage, (), observation)`. In this field layout, the fourth argument occupies the inherited `answer_content` field, while the subclass's `observation` remains `None`. The test log contains errors when tests subsequently access that missing observation. This identifies a compatibility problem; no adapter or Engine patch was made in this documentation-only task.

Other observed failures include:

- The Engine-version assertion requires three numeric components; the selected version is `0.3.5.2`.
- The initial-request equality assertion does not hold across the three conditions on this checkout.
- The synthetic preflight assertion expected 3 calls and observed 4.
- The deployment integration fixture expected `ACCEPTED_VERIFIED` but observed `BUDGET_EXHAUSTED`.
- Expected final-import events and synthetic smoke progress/completion assertions did not hold.

These observations are not a complete diagnosis of every failure and must not be turned into claims about model quality or which Engine change caused the historical smoke outcome. The runtime and tests need a separately scoped compatibility repair; this publication change does not weaken tests to produce a pass.

### Errors reported by the host run

- `test_cli_enabling_credits_blocks_readiness_and_the_next_dispatch`
- `test_malformed_prose_and_schema_violations_fail_without_repair`
- `test_secrets_are_redacted_from_retained_evidence`
- `test_stdin_stream_json_transport_keeps_prompt_out_of_argv`
- `test_structured_invocation_is_isolated_bounded_and_invocation_accounted`
- `test_timeout_output_limit_and_only_owned_processes_are_cleaned_up`
- `test_unknown_usage_is_not_reported_as_zero`
- `test_dispatch_budget_and_timing_are_recorded`
- `test_structured_translation_preserves_full_context_schema_raw_and_usage`

### Failures reported by the host run

- `test_progress_reports_stages_and_invocations_without_content`
- `test_synthetic_end_to_end_smoke_binds_checks_and_feeds_diagnostics_forward`
- `test_preflight_failure_blocks_all_later_live_work_in_plan`
- `test_three_conditions_same_task_hidden_evaluation_absent_and_no_unmetered_judge`
- `test_engine_source_fingerprint_is_reproducible`
- `test_final_engine_events_explicitly_post_run_imports`
- `test_real_engine_restores_better_candidate_and_retains_failures`

## Local-only validation evidence and publication scope

The following generated files are retained locally under `output/publication-validation-20261011/` and are excluded from the repository:

- `harness-tests-sandbox.txt` and `harness-tests-host.txt`: complete logs for both attempts.
- `test-summary.json`: actual host counts and failed/error test names.
- `engine-identity-before.json` and `engine-identity-after.json`: selected identity and source manifests.
- `verified-evidence.json`: independent verification of both historical smokes, bound checks, and journal closure.
- `historical-output-before.json` and `historical-output-after.json`: byte-hash manifests confirming all **293 pre-existing generated evidence files** were unchanged.

Raw smoke/experiment evidence and model responses are not distributed by the public repository. The original smoke and closeout remain local-only references described in [ANTIGRAVITY_INTEGRATION_REPORT.md](ANTIGRAVITY_INTEGRATION_REPORT.md). Both historical runs used `benchmark_eligible=false`, and provider invocations are not underlying Gemini request counts.

Only Harness documentation/publication preparation changed in this task. The separate Engine source fingerprint remained identical, runtime/checker code and tests were not edited, and historical evidence was not rewritten or deleted. The current compatibility failure remains a blocker for claiming support for Engine 0.3.5.2; it does not invalidate the separately recorded historical smoke outcomes.
