# END Engine integration gaps

## v0.2 experiment boundary

The controlled evaluation runner does not repair these Engine interfaces or introduce another internal acceptance gate. Its task-specific ToolVerifier supplies only the declared development checks. Full reference evaluation happens after the condition has returned and submitted its candidate; it neither changes END's selected answer nor sends hidden diagnostics into the controller. The original Engine verdict and external task outcome are recorded separately. Same-model Ollama generator/judge metadata preserves correlation rather than pretending the judges are empirically independent. Task/check binding generalization retains native rollback and final-candidate evidence identity.

> Historical compatibility note (2026-09-30): that check selected Engine **0.3.2**. The note then recorded that 0.3.1 stopped escalating invalid audits to high-severity weaknesses and added explicit accepted-risk criteria, and that 0.3.2 reconciled the final assessment of a restored candidate with later concerns about identical content. Those are dated historical descriptions, not a fresh audit of the current Engine. The gap sections below preserve findings observed on 0.3.0. See [COMPATIBILITY.md](COMPATIBILITY.md) for the actual selected identity, reproduced failing baseline and passing offline Harness repair from 2026-10-12. Current tests retain the resource-stop, missing-required-check and interrupted cognitive-state boundary assertions below; this is not a fresh audit of every historical proposal.

Historical findings were observed against END Engine **0.3.0**, verified then by source inspection and real integration tests. The 2026-10-11 publication changed only Harness documentation. The 2026-10-12 repair adapts Harness interfaces and fixtures while leaving the separate Engine unchanged. These are proposed interfaces for its separate roadmap, not patches made by the Harness.

## Resource-stop semantics

`EndEngine.run` catches ordinary exceptions and records `EXTERNAL_BLOCKER`. A Harness `BudgetExhausted` therefore becomes an Engine blocker. The Harness preserves that result and separately returns `model_attempts_exhausted`, `check_attempts_exhausted`, or `deadline_exhausted` as applicable. The three-request offline run demonstrates this path.

Smallest proposed Engine change: accept a typed external stop signal with a machine-readable category, or add a public admission callback whose resource-exhaustion outcome maps to an Engine budget stop. Do not infer the category from exception text.

## Missing required execution evidence

The Engine's gate conservatively treats some uncertainty: no executed evidence or unverified claims can produce `ACCEPT_PROVISIONALLY`; incomplete evaluation produces `BLOCKED`. It does **not** have a manifest of required check IDs or a concept of required unknown executions.

Real integration tests demonstrate both cases:

- With no registered checker, optimistic synthetic judgments can still produce `ACCEPT_PROVISIONALLY`.
- With the bounded safety checker completed but an additional required check missing, END can still produce `ACCEPT_VERIFIED`.

The Harness records required/completed/missing check coverage per candidate and exposes this limitation in every result. Since v0.1.1 it also supplies explicit final-candidate coverage with artifact binding, PASS/FAIL/error/unknown distinctions, required versus optional checks, and receipt references, while keeping full history separately. It does not rewrite END acceptance or implement another gate. Consumers must read evidence coverage together with the Engine result; `ACCEPT_VERIFIED` is not a statement that every Harness requirement completed.

Smallest proposed Engine change: accept a required-evidence manifest and candidate-bound execution statuses as inputs to the existing gate. Missing, errored, timed-out, or unknown required execution should be explicitly considered there. Keep actual check execution owned by the Harness.

## No incremental cognitive event sink

The public `last_trajectory` snapshot supplies an actual trajectory ID during runtime, but END does not expose a durable event sink or supported full checkpoint/resume mechanism. Its own ledger is saved once at the end. Harness model/check records are live and durable; candidates, judgments, quality decisions, rollback history, and other Engine steps are imported after return with explicit post-run provenance.

An actual subprocess-exit test demonstrates that the provider intent survives while the full Engine trajectory is unavailable. Recovery closes the history, never resumes the cognitive loop.

Smallest proposed Engine change: add a public append-only event observer/sink that receives the trajectory and local IDs at emission time. Full cognitive checkpoint/resume remains a separate larger feature.

## Evidence status and scope expressiveness

`EvidenceArtifact` has a Boolean `passed`, description, targets, source, and optional test ID. It cannot carry execution status, all hashes, configuration, or receipt timing directly. The adapter emits evidence only for validated COMPLETED receipts and keeps a resolvable Harness receipt reference in `source`. Unsupported/error/unknown executions stay in the Harness journal and coverage records.

Model-proposed adversarial tests remain END's original unexecuted proposal records; `check/request_mapped` records and receipts show which registered checks actually ran. The Harness does not mutate old Engine test records or imply that a model description itself executed.

Smallest proposed Engine change: add an optional typed external receipt reference and explicit required execution status, retaining the existing Boolean verdict only for completed execution.

## Opaque judge request coverage

`ModelJudgeProvider` exposes its underlying `ModelProvider`, so the Harness meters each request once and preserves wrapping through `for_run`. Arbitrary `JudgeProvider` implementations can hide several requests in one `evaluate`. Their clone behavior is preserved, but the Harness reports invocation-only visibility and cannot enforce their hidden request/token consumption. The offline demo uses model-backed judges and has full wrapped-request coverage.

Smallest proposed Engine/provider convention: expose all model transports or accept a request middleware factory when constructing/cloning judges. Arbitrary provider-internal retries must likewise be disabled or routed through the wrapped boundary.
