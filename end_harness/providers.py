"""Composition wrappers meter actual synchronous provider request boundaries."""
from dataclasses import asdict
from uuid import uuid4
from .budget import BudgetExhausted, TokenUsage
from .encoding import canonical, diagnostic


class TransientProviderError(RuntimeError):
    """Only explicitly classified transport failures are eligible for retry."""


class BudgetedModel:
    def __init__(self, provider, budget, journal, *, role="generator", max_retries=0, engine_ref=lambda: None):
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        self.provider, self.budget, self.journal = provider, budget, journal
        self.role, self.max_retries, self.engine_ref = role, max_retries, engine_ref

    def metadata(self):
        return {**self.provider.metadata(), "harness_role": self.role, "request_metered": True}

    def for_run(self):
        clone = self.provider.for_run() if hasattr(self.provider, "for_run") else self.provider
        return BudgetedModel(clone, self.budget, self.journal, role=self.role,
                             max_retries=self.max_retries, engine_ref=self.engine_ref)

    def generate(self, request):
        return self._request("generate", request)

    def generate_structured(self, request):
        return self._request("generate_structured", request)

    def _request(self, method, request):
        previous = None
        for attempt in range(self.max_retries+1):
            ref = self.engine_ref()
            try:
                reservation = self.budget.reserve("model")
            except BudgetExhausted:
                self.journal.append("budget/exhausted", self.budget.snapshot(), engine=ref)
                raise
            call_id = str(uuid4())
            call = self.journal.append("model/call", {"role": self.role, "method": method,
                "request": asdict(request), "retry_index": attempt, "retry_of": previous,
                "reservation": asdict(reservation)}, call_id=call_id, engine=ref)
            try:
                self.budget.boundary()
            except BudgetExhausted:
                self.budget.settle(reservation)
                self.journal.append("model/result", {"status": "NOT_DISPATCHED", "usage": None,
                    "usage_provenance": "unknown", "reason": self.budget.stop_cause},
                    call_id=call_id, parent_seq=call.seq, engine=ref)
                raise
            try:
                response = getattr(self.provider, method)(request)
            except Exception as exc:
                usage = self.budget.settle(reservation, TokenUsage.from_report(getattr(exc, "usage", None)))
                self.journal.append("model/result", {"status": "ERROR", **diagnostic(exc),
                    "usage": asdict(usage), "failure_category": getattr(exc, "category", None),
                    "observation": getattr(exc, "observation", None)}, call_id=call_id, parent_seq=call.seq, engine=ref)
                if not isinstance(exc, TransientProviderError) or attempt >= self.max_retries:
                    raise
                previous = call_id
                self.journal.append("model/retry", {"retry_of": call_id, "next_retry_index": attempt+1},
                                    parent_seq=call.seq, engine=ref)
                continue
            usage = self.budget.settle(reservation, TokenUsage.from_report(getattr(response, "usage", None)))
            # Serialization/validation errors occur outside the retry handler.
            try:
                response_data = asdict(response)
                canonical(response_data)
                if not {"content", "usage", "tool_calls"} <= response_data.keys():
                    raise ValueError("Missing ModelResponse fields")
            except (TypeError, ValueError, UnicodeError) as exc:
                self.journal.append("model/result", {"status": "INVALID_RESPONSE", **diagnostic(exc),
                    "usage": asdict(usage)}, call_id=call_id, parent_seq=call.seq, engine=ref)
                raise ValueError("Invalid model response") from exc
            self.journal.append("model/result", {"status": "COMPLETED", "response": response_data,
                "usage": asdict(usage)}, call_id=call_id, parent_seq=call.seq, engine=ref)
            return response
