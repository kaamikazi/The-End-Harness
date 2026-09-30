"""Run tests against the explicit local Engine without package installation."""
import argparse
import os
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--engine-source", type=Path, required=True)
args = parser.parse_args()
project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
os.environ["END_ENGINE_SOURCE"] = str(args.engine_source.resolve())
from end_harness.adapters import load_engine
load_engine(args.engine_source)
suite = unittest.defaultTestLoader.discover(str(project / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
