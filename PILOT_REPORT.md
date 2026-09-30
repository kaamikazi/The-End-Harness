# END Harness v0.2 local-model pilot — blocked at preflight

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Report finalized 2026-09-29. **Model access succeeded, but the frozen development preflight did not produce valid submissions. No held-out task performance comparison was performed.**

Experiment: `output/experiments-v02/78d73497-11b6-46da-bd2f-51881170ac14`.

Origin: **LIVE_LOCAL_MODEL**. This is a record of actual local requests, not mock or replay results. Unrun conditions remain explicitly unrun.

## Model and frozen limits

Local Ollama inventory contained `qwen2.5:1.5b`, `qwen3:4b`, and `qwen3:8b`. The pilot selected the smallest installed completion model, `qwen2.5:1.5b`, Q4_K_M, 986,061,892 bytes, to keep the smoke experiment manageable. Installed digest:

`65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`

Settings: temperature 0, seed 20260928, `num_predict=1024`, `num_ctx=8192`, non-streaming generation, 25-second transport timeout, 1 MiB response bound. Same model/settings and initial request were used across conditions. No downloads, installations, paid or remote model services, credential searches, or model switches occurred.

The manifest was persisted before generation. It planned six development plus twelve held-out cases across three conditions: **54 runs**, at most **522 generation requests**, and a **900-second dispatch deadline**. SINGLE had one request and no development check. SIMPLE_REVISION and END each had 14 model attempts, 4 development-check attempts, and 60 seconds per run. END requested no post-acceptance probe. Post-run initial/final evaluation allowances were separate and identical for both iterative conditions.

The first development scheduling case (seed 100) was the three-condition protocol preflight. Failure there stopped the remaining 51 planned conditions. No extra budget was granted afterward.

## Actual observations

| Condition | Generation attempts | Result | Submitted task artifact | Reference checks executed |
|---|---:|---|---|---:|
| SINGLE | 1 | Transport timeout at about 25.063 s | None | 0 |
| SIMPLE_REVISION | 1 | Transport timeout at about 25.063 s | None | 0 |
| END | 1 | Server returned `done_reason=length` after 1,024 output tokens; adapter rejected incomplete generation | None | 0 |

END's unchanged Engine result was `EXTERNAL_BLOCKER`; it did not reach its reasoning/judgment loop or submit a candidate. END's row elapsed time was about 16.969 s. Experiment journal start-to-end elapsed time was **67.487 s**.

Observed usage:

- **3 actual generation requests**, all for `initial_candidate`; **0 retries**.
- **0 development-check executions** and **0 final-check executions**. Six post-run initial/final submission inspections recorded missing artifacts without running a reference checker.
- The END transport reported **461 input tokens and 1,024 output tokens**. Usage for the two timed-out requests is **unknown**, so these are partial reported totals, not total experiment token consumption.
- **3 dispatched live condition runs**, **51 unrun conditions**, including all **36 held-out condition runs**.
- There were no successful development submissions. These are three protocol/transport failures with missing evidence, not three reference-checked incorrect solutions. Held-out success rates are unavailable, not 0%.

The model may have consumed resources before each timeout. Client timeout does not certify that all server-side work stopped immediately. Cold loading, fixed condition order, model capacity, and the nested structured response envelope can affect these observations; this run does not isolate their causes.

## Preserved evidence

The experiment directory contains the immutable original `manifest.json`, experiment journal, three run journals, native END result/trajectory, raw transport observations, six missing-submission evaluation records, all 54 planned outcome rows, and original JSON/CSV/report outputs.

Original generation-time Harness source fingerprint:

`1ad9ac2dec1657f3e510bdaf200a5485b96cc617a413889141a01992a6d4fbeb`

Raw successful HTTP output and server finish/usage fields are retained even though generation was incomplete. Timeout observations retain their failure classification and any available response prefix. No model output was repaired or promoted to a verified artifact.

## Documented post-preflight corrections

Offline review found two misleading derived labels in the original report: `live_rows` counted planned live-origin rows rather than dispatched runs, and `evaluated_failures` included missing submissions. Those original derived count claims are invalidated. They must not be read as 54 executed live runs or three checked incorrect answers.

Aggregate format 2 separates planned/dispatched live rows and checked incorrect answers from invalid/missing submissions. New sidecars `REPORTING_CORRECTION.json`, `summary_corrected_v2.json`, and `aggregate_corrected_v2.csv` provide corrected historical summaries. Original outcomes, aggregate, report and journal remain unchanged. Summarization makes no model calls.

The future protocol was versioned to `controlled-evaluation/1.1`. It also exposes the same structured development-check diagnostics through END's evidence descriptions that SIMPLE_REVISION receives directly. The old code supplied the Boolean result/scope to END but omitted the detailed observations. No checker executed in this pilot, so that omission did not affect any observed candidate or score. Original protocol and changed Harness source files are archived with the experiment so the original manifest fingerprint can be reconstructed.

Tasks, instructions, seeds, model selection, generation settings and resource caps were not tuned after results. No held-out scores were observed. **No new real-model run was made after the blocker or these corrections.** The current protocol 1.1 is tested offline; there is no claim of a completed live benchmark under it.

## Interpretation and reproduction

This run establishes that local access and durable failure capture work, and that the preflight stops further requests. It provides **no evidence that END improves or worsens task performance relative to simple revision**. The benchmark comparison is incomplete/invalid for performance inference because no task artifacts reached final evaluation.

Original invocation, from `E:\The End Harness`:

```powershell
$HarnessPython = 'C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $HarnessPython -B -m end_harness pilot --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --output output/experiments-v02 --model-requests 14 --check-attempts 4 --run-seconds 60 --max-total-requests 522 --max-seconds 900 --timeout 25 --num-predict 1024 --num-ctx 8192 --seed 20260928 --temperature 0
```

Read-only corrected summary:

```powershell
& $HarnessPython -B -m end_harness summarize output/experiments-v02/78d73497-11b6-46da-bd2f-51881170ac14
```

A future experiment with changed model/limits requires a separately recorded protocol/configuration and fresh output directory. This implementation did not purchase access, download another model, or silently enlarge the failed run's resources.
