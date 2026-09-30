# END Harness v0.2 architecture

## v0.2 experiment layer

`ollama.py` implements the real ModelProvider contract with standard-library HTTP and an explicit installed identity. Successful responses subclass the real Engine `ModelResponse` to retain raw transport observations; failures carry the same observations and usage into the existing linked request-result journal. HTTP calls have no hidden retries. Both generator and `ModelJudgeProvider` use the same visible wrapped request boundary. Same-model identity remains the same in Engine metadata so its independence limitation is preserved.

`tasks.py` owns immutable, versioned task specifications, deterministic split generation, visible instructions/schemas, and limited development check registration. `CheckBinding` is a small trusted configuration for artifact schema, required check IDs, allowed scope texts, exact optional request mappings, and evidence description. The deployment binding remains the default. Arbitrary model-authored checks remain inert. Receipts now include optional explicit task/input hashes in addition to their full configuration hash; old receipts remain readable.

`evaluation.py` is invoked only after a submitted candidate is fixed and the generating run has returned. Its full reference checker is not registered with the Engine or baseline loops. It evaluates exactly the submitted artifact (and separately the initial artifact for retrospective metrics), recording its own journal and receipts. Unknown/error execution remains indeterminate. Engine quality decisions are neither changed nor used as ground truth.

`experiment.py` implements SINGLE and the bounded SIMPLE_REVISION loop, and delegates END to the existing `run_task` with native selection and zero post-acceptance probing. All conditions use the same visible task and initial Engine-compatible response envelope. A parent Budget caps the entire experiment; child budgets preserve per-condition caps and settle usage into the parent without doubling per-run counts. Final evaluation has a separately bounded post-run measurement allowance and never extends generation budgets.

An experiment manifest, including the Harness source hash, controlled Engine identity, installed model digest/settings, tasks/fixture hashes and caps, is persisted before inference. Completed outcomes are written incrementally. Blocked/unrun rows remain explicit in denominators. Aggregation and summarization only read saved outcomes and distinguish live, synthetic and replay origins. The protocol is fixed before held-out evaluation; methodology changes require a new version and retention/invalidation of affected runs. Full details are in `EXPERIMENT_PROTOCOL.md`.

## Ownership and dependency

`run_task(task, RunConfig, generator=..., judge=...)` creates one UUID run, one budget, one journal, one artifact store, and one check executor. It composes an `EngineAdapter` using END's existing constructor interfaces. The Engine retains its cognitive operators, lineage, knowledge state, judgments, quality gate, comparator, termination controller, and rollback. No Engine code is patched, vendored, subclassed to change control flow, or copied.

The dependency is an explicit source directory, validated and loaded by `load_engine`. The adapter pins the initial controlled load's `pyproject.toml` version and deterministic manifest hash of that file and all `end_engine/**/*.py` files. Before/after manifests must agree during initial import. Subsequent calls compare against the pinned identity and return defensive copies; they do not relabel cached modules with a new disk fingerprint. Prior uncontrolled imports, a different source, or source drift require a fresh process. Detected drift invalidates provenance for that process even if the files are later restored. No Engine modules are reloaded or deleted. The inspected Engine has no Git repository; commit remains null. Bytecode creation is disabled before imports. Standard Python import and hashes do not provide atomic protection against concurrent or malicious filesystem mutation.

```text
task -> run_task -> EngineAdapter -> real END Engine
                     |              |
                     |       BudgetedModel transports
                     |              |
                     |       shared Budget + Journal
                     |
               HarnessToolVerifier
                     |
        ArtifactStore -> CheckRegistry -> CheckExecutor
                     |
        candidate-bound ExecutionReceipt -> END EvidenceArtifact
                     |
          END quality gate / comparator / rollback
                     |
        final result + explicitly post-run Engine imports
```

## Modules and contracts

| Module | Implemented contracts and responsibility |
|---|---|
| `runtime.py` | Frozen `RunConfig`, `RunResult`; run ownership and separate Harness/Engine status |
| `coverage.py` | Uniform bound coverage records and deterministic final-candidate evidence selection; no acceptance decisions |
| `budget.py` | Frozen `BudgetLimits`, `Reservation`, `TokenUsage`; admission and settlement |
| `events.py` | `RuntimeEvent`, `EngineRef`, `Journal`; durable JSONL and historical closure |
| `providers.py` | `BudgetedModel`, explicit `TransientProviderError`; request boundary wrapping |
| `artifacts.py` | Frozen `CandidateArtifact`, content-addressed immutable files |
| `checks.py` | `RegisteredCheck`, `CheckOutput`, `ExecutionReceipt`, registry and executor |
| `adapters.py` | `EngineAdapter`, judge adaptation, `HarnessToolVerifier`, trusted target mapping, final imports |
| `encoding.py` | Strict parsing, canonical bytes, hashes, exclusive immutable writes |
| `demo.py` | Labelled synthetic response transports and three offline demonstrations |
| `cli.py` | Demo, read-only inspection, interrupted closure |

Core budget, event, artifact, and check contracts have no Engine imports. The adapter translates Engine data to JSON-compatible results. Synthetic demo transports import Engine request/response fixtures only when explicitly run.

## Request lifecycle and cloning

1. Check the deadline and reserve one model attempt.
2. Append a `model/call` with request, role, retry linkage, and reservation; flush and fsync.
3. Recheck the monotonic deadline immediately before transport dispatch.
4. Invoke the underlying `generate` or `generate_structured` once.
5. Settle usage with reported counters or explicit unknown provenance.
6. Append a linked result or failure and fsync.
7. Retry only a classified transient exception, bounded by retry count and the same budget.

Malformed returned data, validation errors, budget exhaustion, and journal failures are not retried. A result-persistence failure after provider completion cannot cause automatic duplicate execution. Pending reservations remain visible if persistence or the process fails before settlement.

END's `recorded_judge` invokes `for_run`. An exact `ModelJudgeProvider` is translated to `MeteredModelJudge(BudgetedModel(inner))`. Its clone clones the underlying model where supported and preserves the same budget, journal, and reference callback. Counting occurs once at the actual wrapped model request, never again at `evaluate`. Model-provider implementations with hidden retries or internal fan-out must expose those as transport calls or have an explicit coverage limitation; the runtime cannot observe work hidden inside arbitrary user code.

Opaque judges are wrapped only for invocation records and deadline admission. Their metadata and run limitations state that underlying model attempts/tokens are unobservable. They have no hidden automatic retry policy in the Harness.

## Persistence and recovery

Every event contains `schema_version`, `run_id`, `seq`, `timestamp`, `type`, `payload`, `call_id`, `parent_seq`, and optional `engine={trajectory_id,local_id}`. Local IDs are never treated as global IDs. At live model boundaries only the trajectory identity is available; at checker callbacks the actual candidate identity is also available. END's own model-call IDs are retained in post-run imports without inventing a live mapping.

The journal file is opened exclusively in a new UUID directory. Each append serializes one strict JSON record, writes a newline commit marker, flushes, and fsyncs. An append/checkpoint error poisons the writer. This is process-crash durability to the filesystem's fsync guarantees, not a promise about faulty disks or sudden power loss of directory metadata.

Inspection validates committed envelopes, schema version, run IDs, contiguous sequences, UTC timestamps, and call/result pairing. A final unterminated record is reported as a torn tail with byte offset, length, and hash. A malformed newline-terminated record, including the last one, is corruption. Corruption in the middle is never skipped.

Unpaired model, check, and opaque-judge intents become `OUTCOME_UNKNOWN` in the inspection view. An intent may have been followed by dispatch even if no result survived. Missing results never imply success. No action is automatically repeated.

Closure writes `recovery.json`, an immutable, deterministic annotation bound to the SHA-256 of the original journal. Publication uses an fsynced pending file plus atomic replacement. A failed publication can be retried. The original JSONL, including torn bytes, is never rewritten, truncated, or extended. Repeated closure yields the same record. A subsequent change to the original journal invalidates the closure. There is no Engine checkpoint restoration or automatic resume.

After Engine return, its complete snapshot is saved and each original step is imported with `provenance=post_run_import`, import-time event timestamp, and original Engine step/timestamp in the payload. This includes candidates, judgments, gate outcomes, evidence, and rollback records. If the process dies earlier, live runtime calls/results/artifacts/receipts can survive but the full cognitive trajectory is unavailable. Snapshot persistence, import completion, journal closure, summary persistence, and cleanup are independent caller observations. A snapshot saved before failed import remains inspectable without claiming a completed import.

Finalization uses a structured-return API. Ordinary failures are appended to an ordered `failures` list; the first cause stays in `harness_stop_cause`. Cleanup is always attempted when a journal was acquired, and cleanup errors do not replace an earlier error or process cancellation. `run/end` and `result.json` writes are guarded individually. Journal failure poisons the writer; no later error or closure writes are attempted. An available Engine result is retained even when both final writes fail. Preflight provenance errors still raise before starting a run.

Persistence is observational: the caller can confirm a successful return from fsync/write/close, while a file cannot certify its own successful persistence. The `run/end` snapshot omits closure/summary/cleanup confirmation; `result.json` omits its own write and later cleanup confirmation. Each stores a `status_view` naming when the snapshot was taken. Later failures do not rewrite either immutable record. `inspect` separates readable closed history from summary presence/validity and writer-reported closure confirmation. Readable end bytes after an unconfirmed fsync are not relabelled as confirmed persistence. Inspection cannot invent absent failure records.

The event envelope remains 1.0; result/coverage payloads are 1.1. Old histories remain readable. Legacy `journal_complete` is not trusted as closure confirmation, and legacy coverage is not converted into artifact-bound positive evidence. The original report and run artifacts are retained without migration.

## Artifact and receipt binding

Candidate content is UTF-8 encoded exactly and hashed before parsing. The entire content must be one strict JSON object: no prose extraction, duplicate keys, nonfinite/overflowed numbers, invalid Unicode, or trailing JSON documents. The parsed object is canonically serialized with sorted keys and compact separators, then separately hashed. Raw and canonical bytes are stored by their hashes with exclusive writes; an existing different file is an error.

`CandidateArtifact` records original hash, exact tested hash, MIME type, schema version, and parser/canonicalizer version. Check loading rehashes both stored files and verifies that strict parsing of the original yields the tested bytes. Each execution receives a fresh parsed copy. Input or fixture mutation by the checker invalidates its result.

Each immutable receipt includes Harness run/execution IDs, paired Engine identity, artifact metadata and both hashes, check ID/version, fixture hash, status, verdict, supported scopes, mapped targets, structured observations, UTC start/end, monotonic elapsed seconds, and call sequence. The call record also contains the exact fixture/configuration. Receipt files and result events are persisted before the receipt becomes eligible for evidence translation.

Translation verifies issuance in this run, exact candidate/trajectory/content binding, current check version/fixture, persisted receipt bytes, artifact integrity, completed status, and allowed targets. A receipt for identical content in another candidate still cannot be reused. No result caching is performed.

Original UTF-8 hashing is attempted independently from diagnostic generation. Invalid Unicode leaves a null original hash and an explicit unavailable reason; escaped ASCII diagnostics are labelled separately. Adjacent provider/checker/runtime error diagnostics use the same safe representation. Checker input validators are required to preserve bound data/configuration; their hashes are rechecked before dispatch as well as after execution. Receipt persistence failure poisons the shared journal to block subsequent work.

Coverage is recorded uniformly even for malformed JSON, unsupported requests, failed checks, checker errors, and interrupted collection. Each entry carries the run, paired Engine identity, original hash, tested artifact identity, required/optional checks, individual status/verdict/receipt references, and summary lists. Completed FAIL never enters `passed`; required ERROR/TIMEOUT/UNKNOWN or unexecuted checks remain missing. Failed receipt validation cannot become passed coverage.

Final coverage uses the Engine result and public trajectory's `final_candidate_id`, checks returned content consistency, and selects the latest matching collection from this run and artifact. It never substitutes `latest_candidate_id` or merges passes from earlier collections. Repeats retain all history and flag conflicting outcomes. With no usable UTF-8 identity, coverage cannot bind positive evidence. This is reporting only: the Engine's original acceptance result and known required-evidence limitation remain visible.

The generic runtime defaults to `post_acceptance_cycles=0`. Only the labelled offline regression demo explicitly requests one post-acceptance cycle. No Engine default or candidate selection is altered.

## Trusted check scope

`deployment.safety/1` is a finite transition enumerator over inert policy JSON. It explores a fixed fixture of replica counts 2 and 3; initial healthy counts 1..N; depth 3; and success/failure outcomes. A stop transition removes up to `max_unavailable` healthy replicas. The optional guard reserves at least one healthy replica. Success restores the stopped replicas; failure restores them only if the candidate enables rollback. Each transition is evaluated against the healthy-replica invariant. Counterexample traces and transition counts are stored.

The supported claim text describes only that finite enumeration. `PolicyClaimExtractor` supplies the trusted vocabulary through END's supported claim-extractor seam; it does not assert the claim true. Actual receipts determine support or contradiction. The adapter accepts a model-proposed check request only when scenario, expected property, candidate, and already-mapped claim target match its explicit allowlist. Arbitrary model claim IDs never extend scope.

Execution status and task verdict are separate. Only COMPLETED yields PASS/FAIL. Checker errors and timeouts produce no evidence. No v0.1 check declares a performance criterion, so timeouts cannot establish functional failure. The trust boundary is registered checker code over inert data, not a subprocess or temporary-directory sandbox. No external execution workspace exists to restore or discard.

## Adopted reference patterns

The local DeepSeek reference at `477b4f420553e8a52c2fbccc464d7561b239c443` was inspected read-only. Useful ideas were independently implemented: call-before-dispatch journaling, fail-closed checkpoints, linked results, explicit retry classification, output validation, and conservative interrupted outcomes. The relevant inspected sources are `packages/session/session-checkpoint-policy/src/index.ts` and `packages/core/session/src/repair.ts`, alongside the existing architecture analysis. No DeepSeek code, Cordis framework, build, dependency installation, or fork was used.
