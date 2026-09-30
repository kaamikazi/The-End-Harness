from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from end_harness.artifacts import ArtifactStore
from end_harness.budget import Budget, BudgetLimits
from end_harness.checks import CheckExecutor, default_registry
from end_harness.events import Journal
from end_harness.encoding import strict_loads


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "run"
        self.journal = Journal(self.directory, "test-run")
        self.addCleanup(self.journal.close)
        self.budget = Budget(BudgetLimits())
        self.store = ArtifactStore(self.directory / "artifacts")
        self.executor = CheckExecutor(self.journal, self.budget, self.store, default_registry())

    def events(self):
        return [strict_loads(line) for line in self.journal.path.read_bytes().splitlines()]
