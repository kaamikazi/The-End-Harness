# Antigravity (Gemini) provider — integration report

> Publication note: personal usernames in local executable/path examples are generalized as `<user>`. Recorded outcomes and limitations are unchanged. Referenced generated evidence stays local and is excluded from this repository.

Date: 2026-09-29. This version adds the diagnosis of the first live smoke and supersedes the earlier versions of this file. Sections below "Current status" are kept as the history of earlier passes.

## Current status

- **One live smoke has been run**, launched by you after credit overages were confirmed OFF: `output/antigravity-smoke/71532008-8e55-49f4-af8f-3a1086ae9f47`.
  - All 17 provider invocations completed with valid structured output: 3 probes and 14 inside END.
  - END stopped with `EXTERNAL_BLOCKER` / `BLOCKED`; the Harness cause was `model_attempts_exhausted`, with C0 as best.
  - The post-run reference checks PASSed.
- **Offline diagnosis:** [output/diagnosis-71532008/DIAGNOSIS.md](output/diagnosis-71532008/DIAGNOSIS.md), with the Engine handoff in [ENGINE_HANDOFF.md](output/diagnosis-71532008/ENGINE_HANDOFF.md).
  - **Root cause:** the Engine's mandatory revision cycle, an unresolvable evidence-gap weakness, and two Engine audit policies. No Harness transport, feedback, accounting or deadline defect was found.
  - **Harness changes:** a journaled dispatch-budget/timing record, and stderr progress output.
- **Not claimed:** this establishes integration viability only. It says nothing about performance, and benchmark use stays blocked (`benchmark_eligible=false`).
- Every Antigravity test uses the **SYNTHETIC** stand-in [`tests/synthetic_agy.py`](tests/synthetic_agy.py). Harness **149/149 OK**, including 37 Antigravity tests, against END Engine **0.3.2** (135/135 OK). Engine 0.3.1 fixed the audit-severity inflation diagnosed in smoke 71532008, and 0.3.2 reconciles the final assessment of a restored candidate; see `E:\The End Engine\IMPLEMENTATION_REPORT.md`. The smoke has not been repeated.

## Credit-setting correction (latest pass)

**What the official documentation establishes**

- **Sparse persistence.** The [settings page](https://antigravity.google/docs/settings) says: "The CLI leverages **sparse persistence** by writing only values to disk that differ from their system defaults." The settings file is `~/.gemini/antigravity-cli/settings.json`. Dropping `useG1Credits: false` when the CLI saves is therefore documented behaviour, not a defect and not evidence that credits were enabled.
- **CLI setting default.** The [CLI reference](https://antigravity.google/docs/cli/reference/) lists `useG1Credits` as a boolean, default `false`, "*External builds only.*" The [settings page](https://antigravity.google/docs/settings) says: "When enabled (`on`), allows the CLI to use your personal AI credits … if your plan's standard quota is exhausted." The [credits page](https://antigravity.google/docs/cli/credits/) says to set it via `/config` or `/settings`.
- **The operative overage control is a separate user setting.** The [Plans page](https://antigravity.google/docs/plans), section "Overages", says: "Usage of credits once the baseline quota is exhausted for any particular model is controlled by the 'AI Credit Overages' user setting". Its values are **Never** ("wait until the baseline quota refreshes") and **Always**. The page states no location, only that "Baseline quota usage across models can be viewed in the settings page". It also states no default and does not say whether the setting applies to the CLI.
- **Not documented anywhere I could find:**
  - how "AI Credit Overages" relates to `useG1Credits`, or which takes precedence;
  - precedence between global and project settings (the settings page describes a hierarchy but no override rule);
  - which builds count as "External builds".
- **No supported CLI surface reports the account setting.** It isn't in flags, the headless JSON envelope, `agy models` or `settings.json`. The documented [`/credits` panel](https://antigravity.google/docs/cli/commands/credits/) shows balance, usage and purchase links only. A zero credit balance is not treated as evidence that overages are disabled.

**What changed (smallest justified correction).** The literal rule "an explicit `false` must remain in the JSON" was replaced by an effective-setting check, `credit_assessment()`. It has two parts, and both must hold.

1. **Local CLI value, machine-verified** by reading `settings.json`:

   | Local state | Result |
   |---|---|
   | explicit `false` | effectively false |
   | absent | effectively false, by the documented default plus sparse persistence |
   | explicit `true` | **blocks** |
   | non-boolean, malformed, BOM, missing file | **blocks** |

   If the CLI changes the local value to anything other than false during a metadata command, it is reported as `settings_changed_by_cli` and blocks. A `false` → absent change is recorded as "documented sparse persistence of the default" and does not block.

2. **"AI Credit Overages", by your confirmation** through `--account-credit-overages never|always|unconfirmed` (default `unconfirmed`):

   | Value | Result |
   |---|---|
   | `never` | passes this part; recorded as "user confirmation (not machine-verified)" in the manifest |
   | `unconfirmed` | **blocks**: the setting is unreported and its precedence is undocumented |
   | `always` | **blocks**: it conflicts and precedence is undocumented |

   Precedence becomes moot only when every documented surface disables overage.

The check runs before any CLI process, again after the metadata commands, and before every prompt dispatch; a failure raises `configuration_not_established` and no process starts. The file is never rewritten before requests, and there is no unconditional bypass. When the check passes, the `credit_overage` control reads `configured_unverified`, because credit consumption itself is unobservable. `benchmark_eligible` stays `false`, and all tool, browsing, subagent, plugin, fallback and hidden-request disclosures are unchanged.

**Readiness now** (`output/validation-antigravity/antigravity-check-credit-fix.json`, metadata only)

| Item | Result |
|---|---|
| `ready` | `false` |
| Local `useG1Credits` | absent, which resolves to effective `false` (documented default plus sparse persistence) |
| Only blocker | `credits: "AI Credit Overages" user setting is unconfirmed: no supported CLI surface reports it and its precedence relative to useG1Credits is undocumented` |
| Capabilities | READY: version 1.2.13, all flags present, `gemini-3.8-flash-high` listed |
| Invocations | 0 provider invocations; all job processes exited |

**Remaining concrete blocker and the one manual action.** Find the "AI Credit Overages" user setting, confirm it reads **Never**, and set it to **Never** if it doesn't. The docs do not state where this setting lives. Two places are plausible but **unconfirmed**:
- the CLI's own `/config` (alias `/settings`) panel, which is the documented CLI settings surface;
- the settings page of the Antigravity app, where the Plans page says quota usage can be viewed.

If the setting is not visible on any surface, the effective behaviour cannot be established and the smoke stays blocked. The missing evidence would then be a documented or visible location and value for that setting. Passing `--account-credit-overages never` records your confirmation only; the Harness cannot verify it.

## Configuration pass (previous pass)

**Config path used:** `C:\Users\<user>\.gemini\antigravity-cli\settings.json`. This is `%USERPROFILE%\.gemini\antigravity-cli\settings.json`, resolved by `default_settings_path()` from `Path.home()`, which follows `%USERPROFILE%` on Windows. The path is covered by an offline test.

**Starting state.** The file was 59 bytes and held a single key, `trustedWorkspaces` (a list; its values were not printed), with **no `useG1Credits` key**. The earlier readiness result (`credit_overage: violated`) was therefore correct. The Harness read the correct path and the actual `useG1Credits` key, and did not treat the missing key as false.

**Steps performed**

1. Closed the interactive CLI you had open: `agy.exe` PID 32736, started from `cmd.exe`. This was the only `agy` process; nothing else was stopped. The settings file hash was unchanged by closing it.
2. Ran the new tested command `antigravity-disable-credits`, which:
   - backs up the existing file first;
   - adds `"useG1Credits": false` while keeping every other key and value;
   - writes the file atomically and re-reads it to verify;
   - reports only key names and hashes;
   - can never set the key to `true`.

   Result: backup `settings.json.bak`, byte-identical to the original; the new file contained `trustedWorkspaces` unchanged plus `useG1Credits` as a JSON boolean `false`, with no BOM.
3. Relaunched `agy` through the readiness check. The CLI loads settings fresh on every launch.

**Finding: `agy` 1.2.13 removes an explicit `false`**

- The first readiness check read `useG1Credits: false` before launching `agy` and reported `ready: true`. During its `agy models` step, `agy` rewrote `settings.json` back to the original 59 bytes (SHA-256 `4263e3cc0bfc40ee248a4595004fd41397814d30f96f9d459b91617bc413a8c8`) and dropped the key. That `ready: true` in `output/validation-antigravity/antigravity-check-configured.json` is a **false positive from the pre-fix Harness and is invalid**.
- **Cause, confirmed by a read-only string search of `agy.exe`.** The settings struct field is tagged `json:"useG1Credits,omitempty"`. For a boolean, `omitempty` drops `false` (the zero value) whenever the CLI re-saves the file, so this build writes `false` to disk as an absent key. `toolPermission`, `enableTerminalSandbox`, `allowNonWorkspaceAccess`, `modelProvider` and `trustedWorkspaces` carry the same `omitempty` tag.
- **Reproduced.** I re-applied the key (backup `settings.json.bak.1`) and ran the fixed check. `--version` and `--help` left the key intact; `agy models` removed it again (`explicit_false -> absent`).
- **Final state of your files.** `settings.json` equals the original bytes, and both `settings.json.bak` and `settings.json.bak.1` are identical to the original. The net change is the two backup files. No credential, token or unrelated setting was read out, altered or printed.

**Harness defects found and fixed.** The policy itself is unchanged: explicit `false` is still required, and a missing key is never treated as false.

- **Check-then-use gap.** Readiness verified settings only before launching `agy`, and the smoke verified them only at start. Now:
  - the settings are fingerprinted (hash and credit state) after every metadata command;
  - `readiness()` re-verifies them after the CLI has run, and blocks with `settings_rewritten_by_cli:<command>` if they no longer pass;
  - the smoke re-verifies them after the capability commands (`BLOCKED_PREREQUISITE`);
  - every prompt dispatch re-verifies them first and fails closed with `configuration_not_established` without starting a process;
  - each invocation records the settings state afterwards (`credit_setting_removed_by_cli`).
- **Imprecise reasons.** The check now reports distinct states:
  - `file_missing`
  - `unreadable` (malformed JSON, duplicate keys, or not an object)
  - `absent` ("a missing key is never treated as false")
  - `explicit_true`
  - `non_boolean:<type>` (for example the string `"false"`, `0` or `null`)
  - `explicit_false`

  A UTF-8 BOM is also a violation, because the CLI may not read such a file.

**Readiness output after the fix** (`output/validation-antigravity/antigravity-check-after-fix.json`)

| Field | Value |
|---|---|
| `ready` | `false` |
| `provider_invocations` | 0 |
| `benchmark_eligible` | `false` |
| CLI version | `1.2.13` (the `--version` output; the flag is undocumented and informational only) |
| Required flags (`--prompt`, `--output-format`, `--json-schema`, `--model`, `--print-timeout`, `--sandbox`, `--effort`) | all present in `--help` |
| `gemini-3.8-flash-high` | listed by `agy models` (exit 0). This is evidence that the CLI's account session works; your Google AI Pro account was not otherwise inspected. |
| Blocker | `settings_rewritten_by_cli:models: useG1Credits explicit_false -> absent` |
| Settings before the CLI ran | `established`, `explicit_false` |
| Settings after the CLI ran | `not_established`, `absent` |
| `credit_overage` | **`violated` (not resolved)** |
| `automatic_model_fallback` | **`unsupported` (remaining limitation)**: there is no documented control and the serving model is not reported |
| Other blockers for benchmark use | `web_browsing_and_search` and `subagent_delegation`: unsupported. `plugins_skills_mcp`: unsupported (7 global plugins are present). `agent_tool_use_observability` and `hidden_retries_and_internal_loops`: unknown. |
| Process cleanup | all three commands ran in a Windows job object; 0 processes remained active afterwards; temporary workspaces were removed empty |

## Decision from the previous pass (resolved)

The previous pass left a choice between three options. This pass resolves it with the effective-setting check above, which rests on documented sparse persistence plus your confirmation of the account setting. It does not rely on a binary inspection, and it does not rewrite the file before each dispatch.

## Official documentation (verified and quoted in the previous pass)

- **Install:** `irm https://antigravity.google/cli/install.ps1 | iex`, into `C:\Users\<username>\AppData\Local\agy\bin`.
- **Sign-in:** launching `agy` uses the OS keyring, and the browser opens if no session exists. `/logout` signs out.
- **Headless flags:**
  - `-p`/`--print`/`--prompt`, `--output-format`, `--input-format` ("reads prompts on stdin"), `--json-schema`, `--model` ("see `agy models`").
  - `--effort`, `--agent`, `--continue`/`-c`, `--conversation`, `--dangerously-skip-permissions`.
  - `--print-timeout` (default `5m`), and `--sandbox`, documented as "Run with terminal sandbox restrictions enabled".
  - `--help` and `--version` are not documented.
- **`useG1Credits`:** the reference lists a boolean, default `false`, described as "*External builds only.* Uses personal AI credits for model calls once plan quotas are exhausted." The credits page says to set **Use G1 Credits** to **off** "to restrict fallback billing" and gives no default. The first version of this report wrongly said the pages conflict.
- **No documented control for:** automatic model fallback; per-run disabling of browsing, search, subagents or plugins/MCP; temperature, seed or output-token limits; per-invocation request counts; or reporting the serving model.
- **Context loading:** global `~/.gemini/GEMINI.md` and `GEMINI.md`/`AGENTS.md` in the active directory are loaded. Conversations are scoped to the working directory.
- **`useG1Credits` policy:** requiring an explicit `false` is a **conservative project policy, not a confirmed platform requirement**.

## Audit of the adapter (previous pass, still valid)

- **No shell:** `Popen(list, shell=False)` with an absolute `.exe` only.
- **Cleanup touches only the adapter's own processes:** a Windows job object is used, and the POSIX branch fails safe but is untested here.
- **Bounded output and time:** stdout is capped at 1 MiB and stderr at 256 KiB, and each invocation is limited to min(90 s, remaining time).
- **Incomplete or malformed responses are rejected** without repair or retry.
- **Failure categories stay distinct:** authentication, quota, timeout, process, incomplete generation and schema failures are classified with heuristics that ignore harmless credential log lines, and this pass adds `configuration_not_established`.
- **Invocations are never presented as Gemini requests:** results report `invocation_budget` in `unit: provider_invocation`, with `underlying_gemini_requests: null`.
- **Unobservable behaviour is labelled:** hidden retries, loops, tool use and fallback are marked `unknown`, and browsing, delegation, plugins and fallback are marked `unsupported`.
- **`language_server.exe agentapi`** is never used.

## Test results (actually observed in the latest pass)

| Suite | Result | Evidence |
|---|---|---|
| Harness baseline before any Antigravity edits | 112/112 OK | `output/validation-antigravity/harness-tests-before.txt` |
| **Harness, complete** | **146/146 OK** in 38.0 s: 112 pre-existing tests plus 34 SYNTHETIC-fixture Antigravity tests; 0 skipped | `output/validation-antigravity/harness-tests-credit-fix.txt` |
| **Engine, unchanged** | **115/115 OK**, with `-B`, `PYTHONDONTWRITEBYTECODE=1` and a working directory outside the Engine tree | `output/validation-antigravity/engine-tests-credit-fix.txt` |
| Engine source | Identical to the pre-edit snapshot: 148 files, manifest SHA-256 `a397aeeb20d862da17e5fbb71e9e1a5a1e255a95bbe252de45da72b42c3963a3` | `output/validation-antigravity/engine-credit-fix.json` |
| Qwen pilot outputs (`output/experiments-v02/78d73497-11b6-46da-bd2f-51881170ac14`) | Byte-identical to the recorded manifest: 82 files, manifest SHA-256 `e29c708385effdf252e886c46084b784c47317b19db1c2d6164681e7a22670ec` | `output/validation-antigravity/qwen-pilot-manifest.json` |

**Latest pass:** 3 tests were rewritten and 1 added, for a net 34 Antigravity tests. They cover:

- `false` omitted by sparse persistence, during both readiness and prompts, not blocking; the end-to-end synthetic smoke still runs with it.
- The CLI turning credits on (explicit `true`) blocking readiness and the next dispatch.
- An explicit `true` in the file blocking.
- An unconfirmed or `always` account setting blocking readiness, the dispatch and the smoke, before any CLI process.
- An invalid confirmation value being rejected.

**Previous pass** added 7 offline regression tests:

- A missing config file.
- Explicit `false`, explicit `true`, and malformed values (malformed JSON, duplicate keys, non-object, non-boolean values), plus a BOM file.
- Unrelated settings preserved, with backups `.bak` then `.bak.1`.
- A missing file is created, and a malformed file is left untouched.
- Windows `%USERPROFILE%` path resolution, including the CLI command.
- A synthetic CLI that strips the key during `agy models`, then treated as a blocker; the latest pass reinterprets this as sparse persistence.
- Prompt dispatch blocked once the key had been dropped; the latest pass blocks only when the local value is not false.
- The smoke blocking before any prompt when the key was dropped; the latest pass replaced this with the account-setting test.

## Files changed

Overall, relative to the pre-edit snapshot:

- **Added:** `ANTIGRAVITY_INTEGRATION_REPORT.md`, `end_harness/antigravity.py`, `end_harness/antigravity_smoke.py`, `tests/synthetic_agy.py`, `tests/test_antigravity.py`.
- **Modified:** `README.md`, `end_harness/cli.py`, `end_harness/experiment.py`.
- **Removed:** none.

Changed in the latest pass:

- `end_harness/antigravity.py`: `credit_assessment()`, `local_credit_value()`, `credit_transition()`, the `account_credit_overages` config field, the credit control label, and the dispatch guard now using the effective-setting check.
- `end_harness/antigravity_smoke.py`: the credit assessment is part of the offline prerequisites and the post-CLI re-check, and is recorded in the manifest.
- `end_harness/cli.py`: the `--account-credit-overages` option.
- `tests/synthetic_agy.py`: the `enable_credit_setting_on` scenario.
- `tests/test_antigravity.py`, `README.md` and this report.

Changed in the previous pass:

- `end_harness/antigravity.py`: distinct credit states, a BOM check, `default_settings_path`, `disable_g1_credits`, `settings_fingerprint`, `readiness()`, re-verification after the CLI runs and before each dispatch.
- `end_harness/antigravity_smoke.py`: settings re-verified after the capability commands.
- `end_harness/cli.py`: the new `antigravity-disable-credits` command; `antigravity-check` now calls `readiness()`.
- `tests/synthetic_agy.py`: the `omitempty` re-save imitation.
- `tests/test_antigravity.py`, `README.md` and this report.

Outside the repository, on your machine:

- `C:\Users\<user>\.gemini\antigravity-cli\settings.json.bak` and `settings.json.bak.1` were added. Both are identical to the original.
- `settings.json` itself is back to its original bytes, rewritten by `agy`.

## Source fingerprints and smoke records

- The delivered Harness source fingerprint (`end_harness/*.py`) is `ee0b6cec56ee3381a29342e5649aad9ca545b86ee62fb8cb51f56923b70dda14`.
- The earlier zero-invocation blocked records predate the fixes:
  - `output/antigravity-smoke/6571b7bd-8dbe-4cd8-a27f-60b01964a778`, fingerprint `f4a5a72263434515d9428bdb5c97a02f0f2437f30c37e6cf466e44e4253b7cc8`.
  - `output/antigravity-smoke/cd63cf33-2362-4cda-be59-3870d14b7a6d`, fingerprint `b5f41976697f9afabbb50949d17e4c425d80a752ba7d9421ab284190996b021c`.
- No smoke was run in this pass.

## Accounting (design unchanged)

- One budget unit is one **provider invocation**: one `agy` process for one prompt. It is never one Gemini request.
- Underlying requests, hidden retries, loops, tool use and model fallback are unknown and unbounded. Reported `usage` covers a whole invocation.
- The fair request-budget benchmark remains blocked: `run_experiment` raises for this origin.

## Other risk noted for a future smoke

The CLI keeps a `trustedWorkspaces` list, and the adapter runs every invocation in a fresh, untrusted temporary folder. Headless behaviour in an untrusted folder is undocumented. If it prompts or refuses, the first probe will fail and be recorded; the Harness will not add the folders to your trusted list.

## Next step (Windows CMD)

**No smoke or prompt will be sent until you explicitly authorize it.**

1. Open the CLI's settings panel. This sends no prompt, as long as you only use slash commands and don't type a request:

   ```bat
   "%LOCALAPPDATA%\agy\bin\agy.exe"
   ```

   In the CLI, type `/config`. Look for an entry labelled **AI Credit Overages**, set it to **Never** if needed, then exit. If it isn't there, look on the Antigravity app's settings page.

2. Once you have confirmed **Never** on a surface that applies to your account, run the metadata-only readiness check:

   ```bat
   cd /d "E:\The End Harness"
   "C:\Users\<user>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B -m end_harness antigravity-check --executable "%LOCALAPPDATA%\agy\bin\agy.exe" --model gemini-3.8-flash-high --list-models --account-credit-overages never
   ```

3. Expect `"ready": true` with `"benchmark_eligible": false`. The live `antigravity-smoke` stays blocked until you explicitly authorize it.

## Remaining limitations

- **Heuristic classification.** Authentication and quota classification relies on message patterns.
- **Unverifiable CLI behaviour.** Enforcement of `--sandbox` and `allowNonWorkspaceAccess` can't be verified, and the serving model isn't reported.
- **Process containment.** A descendant spawned before the job object is assigned could escape. The POSIX branch is untested. An argv prompt is visible in local process listings.
- **Correlated judging.** Same-model judging is correlated.
- **Scope.** This establishes integration viability only; it says nothing about task performance.
