# END Harness offline compatibility — 2026-10-12

**Result: the focused repair passes the supported Harness suite against the selected Engine 0.3.5.2 checkout: 157 tests in 60.270 seconds, 0 failures, 0 errors, 0 skips, exit 0 after focused PR review.** This is offline integration validation, not live-provider readiness or a performance result.

## Verified baseline and dependency identity

The starting repository was clean on `main` at publication commit `415e38f14cbfb4ef31cfab1009fd9656ac9a90bb`, matching GitHub's `main`. Work is on `fix/engine-0352-compatibility`.

| Field | Actual observed value |
|---|---|
| Explicit separate checkout | `E:\The End Engine` |
| Engine version | `0.3.5.2` |
| Source fingerprint | `29c0bbce13559ea595d34d9c78d4812811bcade144deb6fdbd8a231c4da4fc82` |
| Fingerprint scope | `end_engine/**/*.py` plus `pyproject.toml`; canonical per-file SHA-256 manifest |
| Fresh baseline | 149 tests in 51.645s; 7 failures, 9 errors, 0 skips; exit 1 |
| Initial repair suite | 154 tests in 64.286s; 0 failures, 0 errors, 0 skips; exit 0 |
| Independently retested original PR head | `a3eff41785d78b8a580309a1c93493ac0e9e268b`: 154 tests in 55.901s; 0 failures, 0 errors, 0 skips |
| Reviewed final suite | 157 tests in 60.270s; 0 failures, 0 errors, 0 skips; exit 0 |
| Initial repair preservation | Engine identity/manifest unchanged; all 301 then-existing Harness output files unchanged by SHA-256 |
| Focused review preservation | 326 pre-existing Harness output files and 3044 Engine files unchanged by SHA-256 (Git metadata, virtual environment and Python/test caches excluded from the Engine tree snapshot) |

The earlier publication check on 2026-10-11 ran 149 tests in 69.928s with the same 7 failures and 9 errors. Its separate sandbox attempt was an infrastructure failure. Those logs remain unchanged; the fresh baseline above independently reproduced the reported compatibility failure.

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location 'E:\The End Harness'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
```

The runner was used unchanged with host permissions for temporary synthetic fixtures and loopback fake HTTP servers. No packages were installed. No real model service, account readiness check, live CLI, live smoke or benchmark was launched. Antigravity tests invoke only `tests/synthetic_agy.py`; Ollama transport tests use a local fake HTTP server. The Engine suite was not run.

## Accounting for every original failure and error

### Provider response layout: 9 errors and 2 failures

Engine's additive `ModelResponse.answer_content` displaced the fourth positional argument in each Harness `ObservedResponse` subclass. Transport observations became an answer-boundary value, while `observation` stayed `None`. Both providers now construct responses by keyword; the optional answer boundary stays unset. Existing evidence, redaction, process isolation, usage and accounting assertions remain, with explicit assertions that observations never become answer authority.

These eight observation-access errors raised `TypeError: 'NoneType' object is not subscriptable`:

- Antigravity `AdapterTests.test_cli_enabling_credits_blocks_readiness_and_the_next_dispatch`
- Antigravity `AdapterTests.test_malformed_prose_and_schema_violations_fail_without_repair`
- Antigravity `AdapterTests.test_secrets_are_redacted_from_retained_evidence`
- Antigravity `AdapterTests.test_stdin_stream_json_transport_keeps_prompt_out_of_argv`
- Antigravity `AdapterTests.test_structured_invocation_is_isolated_bounded_and_invocation_accounted`
- Antigravity `AdapterTests.test_timeout_output_limit_and_only_owned_processes_are_cleaned_up`
- Antigravity `AdapterTests.test_unknown_usage_is_not_reported_as_zero`
- Ollama `OllamaTests.test_structured_translation_preserves_full_context_schema_raw_and_usage`

The same defect caused Antigravity `SmokeTests.test_dispatch_budget_and_timing_are_recorded` to compare a missing timing value with an integer (`TypeError`). It also caused `SmokeTests.test_synthetic_end_to_end_smoke_binds_checks_and_feeds_diagnostics_forward` to observe 0 recorded invocations versus 17 actual synthetic dispatches, and `SmokeTests.test_progress_reports_stages_and_invocations_without_content` to miss judgment-completion progress. All three retain their timing/accounting/content-boundary assertions.

### Experiment requests and protocol repair: 2 failures

- `ExperimentTests.test_three_conditions_same_task_hidden_evaluation_absent_and_no_unmetered_judge`: actual Harness incompatibility. The baseline conditions used an older initial prompt/context, while END now includes task/plan authority labels. `adapters.initial_candidate_request` translates the current structured request using Engine's `AssessmentAuthorityPolicy.context`; baseline conditions and candidate protocol probes use it. END still builds its own request. The test continues to compare the entire requests, including schema, and to exclude post-run reference feedback. Protocol is now `controlled-evaluation/1.2`; no historical manifest was changed.
- `ExperimentTests.test_preflight_failure_blocks_all_later_live_work_in_plan`: changed documented Engine behavior. The intentionally invalid fixture remains invalid. Engine's default structured protocol repair dispatches one additional, recorded call: 4 total instead of 3. The test now requires exactly three initial dispatches plus one repair, two accounted END calls, one development task, and no later held-out dispatch. Harness retry settings and all budgets are unchanged.

### Version identity: 1 failure

- `RealEngineIntegrationTests.test_engine_source_fingerprint_is_reproducible`: the independently read version matched the loader, but its three-component regex rejected Engine's four-component patch release. The assertion now permits either three or four numeric components; exact selected-version/path and reproducible fingerprint assertions remain.

### Synthetic rollback contract: 2 failures

- `RealEngineIntegrationTests.test_real_engine_restores_better_candidate_and_retains_failures`: the old synthetic comparison delta no longer drives rejection because current Engine marks pairwise model comparisons advisory. Baseline selected C1 but terminated `BUDGET_EXHAUSTED` after C2's `REVISE` gate, instead of the expected accepted rollback.
- `RealEngineIntegrationTests.test_final_engine_events_explicitly_post_run_imports`: the same fixture mismatch omitted `candidate_rollback`; import itself worked.

The fixture now gives judges a fatal C2 safety finding only when their supplied evidence contains the real failed checker receipt and contract. It cites that exact artifact ID and states the polarity of the checker's actual registered claim. Engine grounds the finding and owns rejection/rollback. Original assertions remain: C0/C2 FAIL, C1 PASS, C2→C1 rollback, accepted C1, retained failure evidence, post-run import ordering, 21 model calls, 3 check attempts. No extra calls, budget increases or Harness gate were introduced.

## Focused evidence and answer-boundary repairs

The trusted registry explicitly declares the built-in checkers' development phase. Each new immutable receipt records that optional declaration; translation rejects a registration/phase mismatch. `CheckContract` derives its ID/version and claims from the validated registration/receipt and binds the exact inspected UTF-8 candidate hash. The canonical JSON hash remains separately recorded; it is not substituted for Engine's inspected-answer hash. Unregistered phase yields no contract; undeclared properties/bounds stay empty. Full checker configuration and its hash remain in the Harness execution records. Development evidence cannot authorize final-task proof.

A new wrapped-answer regression demonstrated an additional adapter defect: `final_coverage` compared END's answer with the raw candidate container. Coverage and END-condition initial submission now use recorded Engine-owned `answer_content` when present, falling back to plain `content` for historical formats. The checker remains bound to the inspected answer; raw trajectory content is retained. No wrapper is guessed or stripped by Harness inspection.

Five new regressions cover original-versus-canonical hash binding, missing phase, phase changes after execution, out-of-scope/final/different-artifact rejection, and wrapped-answer coverage/inspection. Existing unknown-outcome, durable journal/receipt, budget, rollback and historical-format tests remain enabled.

## Focused PR #1 review — 2026-10-12

The reported original PR head was verified locally and on GitHub, and its 154-test result independently reproduced. The five requested contract boundaries were reviewed against the actual Engine interfaces. Two additional concrete defects were demonstrated by regressions before correction:

1. SINGLE/SIMPLE_REVISION submitted raw candidate containers while END submitted its selected answer. Baselines now use Engine's public `extract_answer_region` with the actual adapter-owned `answer_content`, exactly as END does. Raw content and observations remain in durable model-result events. Invalid/nonverbatim boundaries are rejected; prose is not silently converted to JSON. This adds no acceptance gate and changes no Engine policy.
2. Loader identity accepted malformed version metadata, and the test's `$` anchor admitted trailing newlines. Identity now requires a full match of three or four ASCII numeric components; whitespace, suffixes, excess/missing components, non-ASCII digits and non-string values are rejected as unsupported. Prerelease/build version formats are not supported by this numeric version contract. Only actual Engine 0.3.5.2 was runtime-tested; synthetic metadata cases are not other-version compatibility claims.

Three new test methods cover answer-selection equality/raw preservation across all conditions, invalid boundaries/unrepaired prose, and invalid version identity. The existing rollback regression now additionally connects C2's failed receipt ID and original artifact hash to its decisive `SEMANTIC_SUPPORTED` fatal finding, native C2→C1 rollback, C1's PASS receipt, and returned artifact coverage. Its 21-model/3-check accounting remains unchanged.

The review confirmed keyword response construction preserves observations, every Engine-owned repair dispatch goes through the existing metered provider, trusted receipt scope/phase/version/targets and exact inspected artifact bind check contracts, and post-run full reference results stay outside END. Antigravity invocation accounting remains explicitly distinct from unknown Gemini request totals; benchmark eligibility remains false.

Eight actual journals from both historical smokes were inspected read-only with complete closure, no unfinished calls and no torn tails. Existing synthetic historical-format tests also pass. Engine source/evidence and all pre-existing Harness evidence hashes remain unchanged. No blocking Engine defect was established. Final supported suite: **157 tests in 60.270s, 0 failures, 0 errors, 0 skips**, with the same explicit source and bytecode-disabled command above.

New local-only review evidence is under `output/pr1-final-review-20261012/`: original-head/full final logs, regressions before/after correction, source/evidence hash snapshots, original PR diff, and historical inspection results. Raw logs/evidence remain excluded; older validation files are unchanged.

## Scope and remaining limitations

No blocking Engine defect was established. Engine's public response, checker contract, assessment authority and recorded answer interfaces, plus local release reports 0.3.3–0.3.5.2, informed the changes. Engine acceptance, candidate selection, termination, rollback and checker policies were not patched. Reference checks still run only after submission and never enter END.

This repair establishes support only for the exact tested Engine identity above. No previous supported Engine checkout was available: the existing Engine worktree inventory contained only the current checkout. Nothing was downloaded or replaced for cross-version testing. The current request translator is contract-specific; equality regression must be rerun when upgrading Engine. Earlier passing 0.3.0/0.3.2 counts remain historical, not support claims for this repair. Required-check manifest and live cognitive persistence limitations remain visible through the existing integration tests and Harness coverage.

## Local-only validation records

New logs and snapshots are excluded under `output/compatibility-repair-20261012/`: `baseline.txt` contains every original traceback/assertion; `test-summary.json` accounts for all 16 issues; `final-tests.txt` is the final supported suite; `engine-before.json`, `historical-before.json` and `preservation.json` record preservation. Diagnostic runs and intermediate validation failures are retained separately rather than rewritten as passes.

Generated evidence, raw model responses, credentials/account settings, private configuration, caches, bytecode, environments, models, executables and temporary files remain excluded. Source/tests/tools, synthetic policy fixtures and relevant documentation remain included. No excluded local file was deleted, no Engine source was copied, and no license was invented. Historical smoke/closeout evidence remains local only; see [ANTIGRAVITY_INTEGRATION_REPORT.md](ANTIGRAVITY_INTEGRATION_REPORT.md). `benchmark_eligible=false` remains unchanged; provider invocations are not underlying Gemini request counts.
