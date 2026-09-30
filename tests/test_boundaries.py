from dataclasses import replace
from unittest.mock import patch
from end_engine.models.base import ModelRequest, ModelResponse
from end_engine.quality.providers import ModelJudgeProvider
from end_harness.adapters import wrap_judge
from end_harness.budget import Budget, BudgetExhausted, BudgetLimits, TokenUsage
from end_harness.events import JournalError, inspect_run
from end_harness.providers import BudgetedModel, TransientProviderError
from support import RuntimeCase


REQUEST = ModelRequest("boundary-test", "inert test prompt", {})


class CountingProvider:
    def __init__(self, responses=None, counts=None):
        self.responses = list(responses or [ModelResponse({"ok": True})])
        self.counts = counts if counts is not None else []
        self.position = 0

    def metadata(self):
        return {"provider": "unit-fixture", "model": "counter"}

    def for_run(self):
        return CountingProvider(self.responses, self.counts)

    def generate_structured(self, request):
        self.counts.append(request.purpose)
        value = self.responses[self.position]
        self.position += 1
        if isinstance(value, BaseException):
            raise value
        return value

    generate = generate_structured


class ProviderBoundaryTests(RuntimeCase):
    def wrap(self, provider, retries=0):
        return BudgetedModel(provider, self.budget, self.journal, max_retries=retries)

    def test_generator_and_all_judge_roles_share_request_budget_without_double_count(self):
        self.budget = Budget(BudgetLimits(model_attempts=4))
        provider = CountingProvider()
        self.wrap(provider).generate(REQUEST)
        for role in ("primary", "secondary", "adversarial"):
            judge = wrap_judge(ModelJudgeProvider(CountingProvider()), self.budget, self.journal,
                role=role, max_retries=0, engine_ref=lambda: None, limitations=[]).for_run()
            judge.evaluate(REQUEST)
        self.assertEqual(self.budget.attempts["model"], 4)
        with self.assertRaises(BudgetExhausted):
            self.wrap(CountingProvider()).generate(REQUEST)
        self.assertEqual(len([e for e in self.events() if e["type"] == "model/call"]), 4)

    def test_cloned_judge_retains_wrapper_and_same_budget(self):
        provider = CountingProvider()
        wrapped = wrap_judge(ModelJudgeProvider(provider), self.budget, self.journal,
            role="judge", max_retries=0, engine_ref=lambda: None, limitations=[])
        first, second = wrapped.for_run(), wrapped.for_run()
        first.evaluate(REQUEST)
        second.evaluate(REQUEST)
        self.assertEqual(provider.position, 0)
        self.assertEqual(len(provider.counts), 2)
        self.assertEqual(self.budget.attempts["model"], 2)

    def test_retry_charged_and_budget_exhaustion_blocks_next_attempt(self):
        provider = CountingProvider([TransientProviderError("transport"), ModelResponse({})])
        self.budget = Budget(BudgetLimits(model_attempts=1))
        with self.assertRaises(BudgetExhausted):
            self.wrap(provider, retries=3).generate_structured(REQUEST)
        self.assertEqual(len(provider.counts), 1)
        self.assertEqual(self.budget.snapshot()["unknown_usage_calls"], 1)

    def test_retry_success_linked_to_failed_request(self):
        provider = CountingProvider([TransientProviderError("transport"), ModelResponse({}, {"input_tokens": 5})])
        self.wrap(provider, retries=1).generate_structured(REQUEST)
        calls = [e for e in self.events() if e["type"] == "model/call"]
        self.assertEqual(calls[1]["payload"]["retry_of"], calls[0]["call_id"])
        self.assertEqual(self.budget.snapshot()["reported_token_totals"], {"input_tokens": 5})
        self.assertEqual(self.budget.snapshot()["unknown_usage_calls"], 1)

    def test_retry_bound_is_finite(self):
        provider = CountingProvider([TransientProviderError("a"), TransientProviderError("b"), ModelResponse({})])
        with self.assertRaises(TransientProviderError):
            self.wrap(provider, retries=1).generate(REQUEST)
        self.assertEqual(len(provider.counts), 2)

    def test_validation_failure_is_not_retried(self):
        provider = CountingProvider([ValueError("invalid response"), ModelResponse({})])
        with self.assertRaises(ValueError):
            self.wrap(provider, retries=10).generate(REQUEST)
        self.assertEqual(len(provider.counts), 1)

    def test_malformed_return_is_linked_failure_without_retry(self):
        provider = CountingProvider([{"not": "a ModelResponse"}, ModelResponse({})])
        with self.assertRaisesRegex(ValueError, "Invalid model response"):
            self.wrap(provider, retries=10).generate(REQUEST)
        self.assertEqual(len(provider.counts), 1)
        self.assertEqual(self.events()[-1]["payload"]["status"], "INVALID_RESPONSE")
        self.assertEqual(inspect_run(self.directory)["unfinished_calls"], [])

    def test_missing_invalid_and_reported_zero_usage_are_distinct(self):
        for usage in (None, {}, {"input_tokens": -1}, {"input_tokens": True}):
            self.assertEqual(TokenUsage.from_report(usage), TokenUsage("unknown", None))
        self.assertEqual(TokenUsage.from_report({"input_tokens": 0}).provenance, "reported")
        provider = CountingProvider([ModelResponse({}, None)])
        self.wrap(provider).generate(REQUEST)
        self.assertIsNone(self.budget.snapshot()["reported_token_totals"])
        self.assertEqual(self.events()[-1]["payload"]["usage"], {"provenance": "unknown", "tokens": None})

    def test_estimates_are_separate_and_do_not_establish_token_ceiling(self):
        reservation = self.budget.reserve("model")
        self.budget.settle(reservation, TokenUsage("estimated", (("output_tokens", 12),)))
        summary = self.budget.snapshot()
        self.assertIsNone(summary["reported_token_totals"])
        self.assertEqual(summary["estimated_token_totals"], {"output_tokens": 12})
        self.assertFalse(summary["token_ceiling_enforced"])

    def test_failed_request_can_report_nonzero_consumption(self):
        error = TransientProviderError("after consumption")
        error.usage = {"input_tokens": 8}
        with self.assertRaises(TransientProviderError):
            self.wrap(CountingProvider([error])).generate(REQUEST)
        self.assertEqual(self.budget.snapshot()["reported_token_totals"], {"input_tokens": 8})

    def test_deadline_blocks_subsequent_dispatch(self):
        clock = [0.0]
        self.budget = Budget(BudgetLimits(deadline_seconds=1), clock=lambda: clock[0])
        provider = CountingProvider([ModelResponse({}), ModelResponse({})])
        wrapped = self.wrap(provider)
        wrapped.generate(REQUEST)
        clock[0] = 1.0
        with self.assertRaises(BudgetExhausted):
            wrapped.generate(REQUEST)
        self.assertEqual(len(provider.counts), 1)

    def test_deadline_expiring_during_checkpoint_blocks_dispatch(self):
        clock = [0.0]
        self.budget = Budget(BudgetLimits(deadline_seconds=1), clock=lambda: clock[0])
        original = self.journal.checkpoint
        def slow_checkpoint():
            original()
            clock[0] = 2.0
        provider = CountingProvider()
        with patch.object(self.journal, "checkpoint", slow_checkpoint), self.assertRaises(BudgetExhausted):
            self.wrap(provider).generate(REQUEST)
        self.assertEqual(provider.counts, [])
        self.assertEqual(self.events()[-1]["payload"]["status"], "NOT_DISPATCHED")

    def test_checkpoint_failure_blocks_dispatch_and_poison_prevents_retry(self):
        provider = CountingProvider()
        with patch.object(self.journal, "checkpoint", side_effect=OSError("disk failed")):
            with self.assertRaises(JournalError):
                self.wrap(provider, retries=10).generate(REQUEST)
        with self.assertRaises(JournalError):
            self.wrap(provider).generate(REQUEST)
        self.assertEqual(provider.counts, [])
        self.assertTrue(self.journal.failed)

    def test_result_checkpoint_failure_does_not_repeat_completed_provider_work(self):
        original = self.journal.checkpoint
        checkpoints = []
        def fail_result():
            checkpoints.append(1)
            if len(checkpoints) == 2:
                raise OSError("result fsync failed")
            original()
        provider = CountingProvider()
        with patch.object(self.journal, "checkpoint", fail_result), self.assertRaises(JournalError):
            self.wrap(provider, retries=10).generate(REQUEST)
        self.assertEqual(len(provider.counts), 1)

    def test_opaque_judge_clones_but_reports_coverage_limitation(self):
        from end_engine.quality.mock import MockJudgeProvider
        opaque = MockJudgeProvider(scripted={"boundary-test": [{"ok": True}]})
        limitations = []
        wrapped = wrap_judge(opaque, self.budget, self.journal, role="primary", max_retries=2,
                             engine_ref=lambda: None, limitations=limitations).for_run()
        wrapped.evaluate(REQUEST)
        self.assertEqual(len(limitations), 1)
        self.assertIn("not bounded", limitations[0])
        self.assertEqual(self.budget.attempts["model"], 0)
        self.assertEqual(inspect_run(self.directory)["unfinished_calls"], [])
