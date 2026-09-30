# END Harness v0.2 — frozen controlled evaluation protocol

Current protocol `controlled-evaluation/1.1`; task generator `compact-tasks/1`. The original protocol 1 was written before any v0.2 model inference and is archived with the blocked pilot as `PROTOCOL_original_v1.md`. No held-out inference occurred. Version 1.1 corrects reporting denominators and makes the full permitted development-feedback payload visible through END's evidence description, matching SIMPLE_REVISION's feedback content. Tasks, prompts, seeds, model selection and resource limits were not tuned in response to scores. The old pilot and its source are preserved; it is not a valid performance comparison, and no new real-model run was made after the preflight blocker. Any methodology change after viewing held-out scores requires a new protocol/version and retained, invalidated prior results; no successful seeds are selected afterward.

## Question and conditions

Does real-model task performance differ between a simple revision policy and the existing END controller under comparable request budgets? END is not presumed better.

| Condition | Policy | Model request cap | Development check cap | Run deadline |
|---|---|---:|---:|---:|
| SINGLE | One logical initial response; no development feedback | 1 | 0 | 60 s |
| SIMPLE_REVISION | Latest submitted candidate; stop at development PASS, exception, or budget | 14 | 4 | 60 s |
| END | Real local Engine, normal mode, max 2 cycles, no branching, no post-acceptance probe; native selection/rollback | 14 | 4 | 60 s |

All requests, including END's verifier, adversarial tests, primary/adversarial judgments and comparisons, consume the same run and experiment request budgets. Hidden retries are disabled; this protocol requests zero automatic retries. SINGLE is explicitly the lower-resource baseline. The iterative conditions are **request-budget-matched, not equal-compute**. Each condition receives the identical visible task information, output requirements, initial response envelope and initial request. Revision/control prompts differ by policy. END gets no extra reference answers or visible cases.

Only registered trusted checkers inspect inert JSON. No generated code, command execution, tool agent, training export, model promotion, UI or new quality gate is involved.

## Frozen tasks and information separation

There are six development cases: seeds 100, 101, 102 in each of two families. There are twelve held-out cases: seeds 1000–1005 in each family. Task IDs, instruction, input, output schema, development checker interface, final required checks, split/seed, task/input/fixture hashes and generator version are recorded. Duplicate instances (ignoring ID/split/seed labels) are rejected across the entire suite. Shared templates limit generalization, even with disjoint instances.

Scheduling: four jobs with durations and resource demands, directed acyclic precedence, capacity 2, integer starts, and an explicit horizon. Every job occurs exactly once, completes in the horizon, respects precedence, and never exceeds simultaneous capacity. Any feasible schedule suffices; makespan optimality is not a hidden requirement.

Record transformation: eight records; filter active rows at an inclusive value threshold, group by the named field, compute sums/counts, omit empty groups, and order by descending total then ascending group. The schema and every output requirement are in the instruction/input.

The development checker is deliberately limited and identically available to both iterative conditions. Scheduling development checks cover schema, IDs, and precedence; final evaluation additionally checks capacity and horizon. Record development checks cover schema, unique groups, and output ordering; final evaluation independently computes the full filtered aggregates. These omitted development checks are disclosed as requirements in the task; no hidden rule is added.

The entire final evaluator module is called only after a condition returns and its submitted content is fixed. Initial and final artifacts are evaluated afterward, independently. Final diagnostics never enter any generator, judge, or controller request. Models have no filesystem or tool access to evaluation files. Development and final receipts bind artifact hashes, task/input hashes, checker version and full configuration hash. END's acceptance result is retained verbatim alongside the external experimental outcome.

## Model and transport

Discovery is limited to the documented local endpoint `http://127.0.0.1:11434/api/tags`; explicit endpoint overrides must still be loopback HTTP. No proxies, redirects, remote services, cloud model selection, credential search, installation or downloads are used. `/api/show` checks completion capability for the installed selection.

For this machine's first pilot, the selected installed model is `qwen2.5:1.5b` (Q4_K_M, 986,061,892 bytes), digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`. It is the smallest installed completion model; the alternatives discovered were `qwen3:4b` and `qwen3:8b`. This choice is for a manageable smoke experiment, not an accuracy claim. No model switch is made after held-out outcomes.

Generation settings for every condition/role: temperature 0, seed 20260928, `num_predict=1024`, `num_ctx=8192`. The same seed is a repeatability aid, not a guarantee of bitwise deterministic inference. Structured requests send the schema via Ollama `format` and include complete prompt/context/schema in the prompt. The adapter validates the raw response and never fills missing model fields or repairs JSON. The Engine response envelope contains the actual model-produced `content` string; no oracle response is substituted.

`stream=false`; finite transport timeout 25 s; maximum HTTP body 1 MiB. Raw response bytes/output, validation result, server finish status, returned model, installed digest/settings, elapsed time and available token counters are retained. Oversized bodies retain only a labelled bounded prefix; partial bodies and length-stopped generations are failures. Missing token counters remain unknown. Runtime deadlines prevent subsequent dispatch; they do not forcibly terminate arbitrary Python. HTTP operations have finite socket timeouts and total-read deadline checks; the wall-clock experiment boundary may be exceeded by an in-flight bounded operation and final persistence/evaluation. No hard wall-clock cancellation guarantee is claimed.

Same-model judging is procedurally separate but correlated, not independent empirical correctness. Ground truth comes from deterministic task evaluation.

Official documentation consulted before adapter implementation:

- [Local API base URL](https://docs.ollama.com/api/introduction).
- [GET /api/tags model inventory and digests](https://docs.ollama.com/api/tags).
- [POST /api/show capabilities](https://docs.ollama.com/api-reference/show-model-details).
- [POST /api/generate request and response fields](https://docs.ollama.com/api/generate).
- [Structured output schemas and validation](https://docs.ollama.com/capabilities/structured-outputs).
- [Generation parameters](https://docs.ollama.com/modelfile).

## Overall pilot bounds and preflight

The pilot plans 18 tasks × 3 conditions = **54 runs**: six development cases followed by twelve held-out cases. The first development task across three conditions is the small protocol preflight (at most 29 model requests). If it cannot exchange valid structured candidates/control responses, later live calls stop; final task incorrectness alone does not fail preflight. The remaining development cases run before held-out cases. Protocol failures in development also prevent entering held-out evaluation.

Maximum total model requests: **522** (`18 × (1+14+14)`). Maximum configured experiment duration: **900 s**, checked at dispatch boundaries, with the transport/finalization limitation above. Iterative development checking allows at most 144 actual checker executions across the 36 iterative runs. Each run reserves a separate measurement allowance of one final checker per initial/final artifact (at most 108 evaluator executions). Evaluation is post-run measurement cost and never creates more generation budget or feedback. Both iterative conditions have the same 4+2 total check allowances. Actual request, token, check, retry and elapsed costs are reported.

The manifest and initial experiment checkpoint are persisted before generation. A spent global budget blocks subsequent conditions; unrun task/condition rows remain in the planned denominator with null outcomes. No condition receives extra budget after failure. The fixed order SINGLE → SIMPLE_REVISION → END is recorded; warm-up/cache/order effects limit latency comparisons. This protocol is a smoke experiment, not a statistically conclusive benchmark.

## Metrics and failure treatment

Primary task success is valid output and all required final checks passing on that exact submitted artifact. Engine verdicts and development PASS are never substituted. Missing results/evidence are not successes. Checker/evaluator errors are indeterminate, not model-correctness verdicts.

Retain schema/parse failure, incorrect answer/constraint, missing evidence, budget exhaustion, provider/transport failure, runtime failure, and evaluator failure separately. Failures can coexist with an eventually correct submitted artifact; task correctness and execution completion are distinct. Report initial/final correctness, correct-to-incorrect and incorrect-to-correct transitions, role-level requests/retries, reported tokens and per-counter usage coverage, development/evaluation checks, elapsed time, and accepted Engine verdicts that disagree with final outcomes.

Reports include raw counts, finished/evaluated/indeterminate/unrun denominators, paired task-level results and all failures. No significance or broad intelligence claim is made. `LIVE_LOCAL_MODEL`, `SYNTHETIC_FIXTURE`, and `REPLAYED_RESPONSE` are distinct origins; nonlive successes never enter live-model counts. Summarizing saved outcomes does not call a model or constitute a new experiment.

Aggregate format 2 distinguishes `planned_live_rows` from `live_rows` that actually dispatched requests, and separates `unsuccessful_submissions`, `evaluated_failures`, and `invalid_or_missing_submissions`. Original format-1 aggregate fields grouped these concepts too broadly and must not be used as counts of completed model evaluations. The retained pilot's correction sidecar and `aggregate_corrected_v2.json` invalidate/replace those derived count claims without rewriting original artifacts or inventing new responses.

## Reproducible commands

From the project directory, using a Python 3.11+ executable (`$HarnessPython` below):

```powershell
& $HarnessPython -B -m end_harness discover-models
& $HarnessPython -B -m end_harness preflight --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --max-total-requests 29 --max-seconds 180
& $HarnessPython -B -m end_harness develop --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --max-total-requests 174 --max-seconds 360
& $HarnessPython -B -m end_harness pilot --engine-source 'E:\The End Engine' --model 'qwen2.5:1.5b' --output output/experiments-v02
& $HarnessPython -B -m end_harness summarize 'output/experiments-v02/<experiment-id>'
& $HarnessPython -B tools/run_tests.py --engine-source 'E:\The End Engine'
```

The `pilot` command includes its development preflight; running the separate preflight/develop commands is optional and produces separate labelled experiments. Every invocation creates a fresh UUID directory, immutable manifest, experiment journal, per-run journals/candidates/receipts/results, post-run evaluations, per-task outcomes, JSON/CSV aggregates and a readable report. Historical runs and earlier reports are preserved.
