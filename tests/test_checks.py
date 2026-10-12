from dataclasses import replace
from unittest.mock import patch
from end_engine.core.state import Candidate, now
from end_engine.cognition.state import Claim
from end_engine.quality.state import AdversarialTest
from end_harness.adapters import HarnessToolVerifier
from end_harness.budget import BudgetExhausted, BudgetLimits, Budget
from end_harness.checks import (POLICY_CLAIM, CheckExecutor, CheckOutput, CheckRegistry, default_registry)
from end_harness.demo import candidate_text
from end_harness.encoding import canonical, strict_loads
from end_harness.events import EngineRef, JournalError
from support import RuntimeCase


class CheckTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.ref = EngineRef("real-test-trajectory-id", "C1")
        self.mappings = (("CL001", POLICY_CLAIM),)
        self.artifact = self.store.capture(candidate_text("improved"))

    def execute(self, artifact=None):
        return self.executor.execute("deployment.safety", artifact or self.artifact,
                                     engine=self.ref, target_scopes=self.mappings)

    def checker(self, body):
        spec = replace(default_registry().get("deployment.safety"), execute=body)
        self.executor.registry = CheckRegistry([spec])

    def test_actual_transition_enumeration_rejects_regression_and_keeps_all_receipts(self):
        receipts = [self.execute(self.store.capture(candidate_text(name)))
                    for name in ("faulty", "improved", "regressed")]
        self.assertEqual([r.verdict for r in receipts], ["FAIL", "PASS", "FAIL"])
        self.assertTrue(strict_loads(receipts[0].observations_json)["counterexamples"])
        self.assertGreater(strict_loads(receipts[1].observations_json)["transitions_checked"], 0)
        self.assertEqual(len(list((self.directory / "receipts").glob("*.json"))), 3)

    def test_original_hash_and_exact_tested_hash_have_distinct_meaning(self):
        spaced = self.store.capture(' { "x" : 1 } ')
        compact = self.store.capture('{"x":1}')
        self.assertNotEqual(spaced.candidate_hash, compact.candidate_hash)
        self.assertEqual(spaced.tested_hash, compact.tested_hash)
        self.assertEqual(self.store.load(spaced), {"x": 1})

    def test_strict_parser_rejects_ambiguous_data_without_repair(self):
        for content in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '```json\n{}\n```', '{} {}', '[]', '{"x":"\\ud800"}'):
            with self.subTest(content=content), self.assertRaises((ValueError, UnicodeError)):
                self.store.capture(content)

    def test_invalid_policy_schema_is_unexecuted_and_uncharged(self):
        for data in ({}, {**strict_loads(candidate_text("improved")), "max_unavailable": True}):
            artifact = self.store.capture(canonical(data).decode())
            self.assertIsNone(self.execute(artifact))
        self.assertEqual(self.budget.attempts["check"], 0)
        self.assertEqual(self.events()[-1]["payload"]["reason"], "invalid_input")

    def test_unknown_check_is_recorded_but_never_executed(self):
        self.assertIsNone(self.executor.execute("shell.rm", self.artifact))
        self.assertEqual(self.budget.attempts["check"], 0)
        self.assertEqual(self.events()[-1]["payload"]["reason"], "unknown_check")

    def test_unsupported_target_scope_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "Unsupported claim"):
            self.executor.execute("deployment.safety", self.artifact,
                                  target_scopes=(("arbitrary", "production is safe"),))
        self.assertEqual(self.budget.attempts["check"], 0)

    def test_checker_error_and_timeout_are_not_failed_candidate_evidence(self):
        verifier = HarnessToolVerifier(self.executor, lambda: self.ref)
        for error in (RuntimeError("checker bug"), TimeoutError("trusted checker timeout")):
            def body(data, config):
                raise error
            self.checker(body)
            receipt = self.execute()
            self.assertIn(receipt.status, ("ERROR", "TIMEOUT"))
            self.assertIsNone(receipt.verdict)
            self.assertEqual(receipt.targets, ())
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                verifier.evidence(receipt, self.artifact, self.ref, self.mappings)
        self.assertEqual(self.budget.attempts["check"], 2)  # No automatic retries.

    def test_malformed_checker_output_never_becomes_evidence(self):
        for output in (True, CheckOutput("PASS", (POLICY_CLAIM,), '[]'),
                       CheckOutput("PASS", ("arbitrary scope",), '{}'),
                       CheckOutput("PASS", (POLICY_CLAIM,), '{"a":1,"a":2}')):
            with self.subTest(output=output):
                self.checker(lambda data, config: output)
                receipt = self.execute()
                self.assertEqual(receipt.status, "ERROR")
                self.assertIsNone(receipt.verdict)

    def test_mutation_of_artifact_by_checker_is_error(self):
        def mutate(data, config):
            data["max_unavailable"] = 3
            return CheckOutput("PASS", (POLICY_CLAIM,), '{}')
        self.checker(mutate)
        self.assertEqual(self.execute().status, "ERROR")
        self.assertEqual(self.store.load(self.artifact)["max_unavailable"], 1)

    def test_stale_receipt_rejected_for_different_content_candidate_trajectory_or_run(self):
        receipt = self.execute()
        alternatives = [(self.store.capture(candidate_text("regressed")), self.ref),
                        (self.artifact, replace(self.ref, local_id="C2")),
                        (self.artifact, replace(self.ref, trajectory_id="other"))]
        for artifact, ref in alternatives:
            with self.assertRaisesRegex(ValueError, "Stale"):
                self.executor.validate_receipt(receipt, artifact, ref, self.mappings)
        with self.assertRaisesRegex(ValueError, "foreign"):
            self.executor.validate_receipt(replace(receipt, run_id="other"), self.artifact, self.ref, self.mappings)

    def test_artifact_disk_tampering_is_detected(self):
        receipt = self.execute()
        (self.store.directory / (self.artifact.tested_hash + '.json')).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.executor.validate_receipt(receipt, self.artifact, self.ref, self.mappings)

    def test_persisted_receipt_tampering_is_detected(self):
        receipt = self.execute()
        (self.directory / "receipts" / (receipt.execution_id + '.json')).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, "Persisted receipt mismatch"):
            self.executor.validate_receipt(receipt, self.artifact, self.ref, self.mappings)

    def test_unknown_or_forged_execution_is_not_positive_evidence(self):
        receipt = self.execute()
        verifier = HarnessToolVerifier(self.executor, lambda: self.ref)
        with self.assertRaises(ValueError):
            verifier.evidence(replace(receipt, status="UNKNOWN"), self.artifact, self.ref, self.mappings)
        with self.assertRaises(ValueError):
            verifier.evidence(replace(receipt, execution_id="never-issued"), self.artifact, self.ref, self.mappings)

    def test_fixture_version_and_claim_target_binding_checked_at_translation(self):
        receipt = self.execute()
        with self.assertRaisesRegex(ValueError, "targets"):
            self.executor.validate_receipt(receipt, self.artifact, self.ref, ())
        spec = replace(self.executor.registry.get("deployment.safety"), version="2")
        self.executor.registry = CheckRegistry([spec])
        with self.assertRaisesRegex(ValueError, "configuration mismatch"):
            self.executor.validate_receipt(receipt, self.artifact, self.ref, self.mappings)

    def test_model_authored_command_and_arbitrary_claim_id_cannot_expand_scope(self):
        verifier = HarnessToolVerifier(self.executor, lambda: self.ref)
        candidate = Candidate("C1", None, 0, candidate_text("improved"), now())
        claims = (Claim("CL001", POLICY_CLAIM, "technical", "C1"),
                  Claim("CL999", "All production deployments are safe", "technical", "C1"))
        tests = (AdversarialTest("AT1", "C1", "CL999", "registered:deployment.safety", POLICY_CLAIM),
                 AdversarialTest("AT2", "C1", "CL001", "rm -rf /", POLICY_CLAIM))
        evidence = verifier.collect("task", candidate, tests, claims)
        self.assertEqual(evidence[0].targets, ("CL001",))
        self.assertEqual(len([e for e in self.events() if e["type"] == "check/unexecuted"]), 2)
        self.assertIn("receipts/", evidence[0].source)

    def test_engine_contract_uses_issued_receipt_scope_and_original_inspected_hash(self):
        content = '  ' + candidate_text('improved') + '\n'
        artifact = self.store.capture(content)
        receipt = self.execute(artifact)
        evidence = HarnessToolVerifier(self.executor, lambda: self.ref).evidence(
            receipt, artifact, self.ref, self.mappings)
        contract = evidence.contract
        self.assertEqual(contract.check_id, receipt.check_id)
        self.assertEqual(contract.version, receipt.check_version)
        self.assertEqual(contract.claims, receipt.supported_scopes)
        self.assertEqual(contract.phase, 'development')
        self.assertEqual(contract.artifact_sha256, artifact.candidate_hash)
        self.assertNotEqual(contract.artifact_sha256, artifact.tested_hash)
        self.assertEqual(contract.properties, ())
        self.assertEqual(contract.bounds, '')  # No separate semantic bounds declared.

    def test_phase_cannot_be_changed_after_execution_to_expand_authority(self):
        receipt = self.execute()
        self.assertEqual(receipt.evidence_phase, 'development')
        stored = strict_loads((self.directory/'receipts'/(receipt.execution_id+'.json')).read_bytes())
        self.assertEqual(stored['evidence_phase'], 'development')
        spec = replace(self.executor.registry.get('deployment.safety'), evidence_phase='final')
        self.executor.registry = CheckRegistry([spec])
        with self.assertRaisesRegex(ValueError, 'registration/configuration mismatch'):
            HarnessToolVerifier(self.executor, lambda: self.ref).evidence(
                receipt, self.artifact, self.ref, self.mappings)

    def test_unregistered_phase_remains_missing(self):
        spec = replace(default_registry().get('deployment.safety'), evidence_phase=None)
        self.executor.registry = CheckRegistry([spec])
        receipt = self.execute()
        evidence = HarnessToolVerifier(self.executor, lambda: self.ref).evidence(
            receipt, self.artifact, self.ref, self.mappings)
        self.assertIsNone(evidence.contract)
        self.assertEqual(evidence.targets, ('CL001',))

    def test_development_contract_cannot_prove_final_success_or_another_artifact(self):
        from end_engine.quality.integrity import scope_gap
        receipt = self.execute()
        evidence = HarnessToolVerifier(self.executor, lambda: self.ref).evidence(
            receipt, self.artifact, self.ref, self.mappings)
        claim = Claim('CL001', POLICY_CLAIM, 'technical', 'C1')
        self.assertIsNone(scope_gap(evidence, claim, self.artifact.candidate_hash))
        self.assertEqual(scope_gap(evidence, claim, '0'*64), 'checked a different artifact')
        self.assertIsNotNone(scope_gap(evidence, replace(claim, text='All tests pass'),
                                      self.artifact.candidate_hash))
        # Even an exact final-scope registration still needs an actual final phase.
        final = replace(evidence, contract=replace(evidence.contract, claims=('All tests pass',)))
        self.assertEqual(scope_gap(final, replace(claim, text='All tests pass'),
            self.artifact.candidate_hash), 'development-scope evidence cannot support a final-task claim')

    def test_no_cross_candidate_cache_even_for_identical_content(self):
        self.execute()
        self.execute()
        self.assertEqual(self.budget.attempts["check"], 2)
        self.assertEqual(len(self.executor.receipts), 2)

    def test_check_budget_and_checkpoint_fail_closed(self):
        self.executor.budget = Budget(BudgetLimits(check_attempts=0))
        with self.assertRaises(BudgetExhausted):
            self.execute()
        self.executor.budget = self.budget
        calls = []
        self.checker(lambda data, config: calls.append(1))
        with patch.object(self.journal, "checkpoint", side_effect=OSError("disk full")):
            with self.assertRaises(JournalError):
                self.execute()
        self.assertEqual(calls, [])
