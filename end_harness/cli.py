"""Offline CLI; inspection never imports END or re-executes work."""
import argparse
import json
from pathlib import Path
import sys
from .demo import run_demo
from .events import close_interrupted, inspect_run
from .encoding import diagnostic


def main(argv=None):
    parser = argparse.ArgumentParser(prog="end-harness")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run real Engine with SYNTHETIC offline fixtures")
    demo.add_argument("--engine-source", type=Path, required=True)
    demo.add_argument("--output", type=Path, default=Path("output"))
    for name in ("inspect", "close-interrupted"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
    discover = commands.add_parser('discover-models', help='Read the local Ollama model inventory; no inference or download')
    discover.add_argument('--endpoint', default='http://127.0.0.1:11434')
    for name in ('preflight', 'develop', 'pilot'):
        command = commands.add_parser(name)
        command.add_argument('--engine-source', type=Path, required=True)
        command.add_argument('--model', required=True)
        command.add_argument('--endpoint', default='http://127.0.0.1:11434')
        command.add_argument('--output', type=Path, default=Path('output/experiments'))
        command.add_argument('--model-requests', type=int, default=14)
        command.add_argument('--check-attempts', type=int, default=4)
        command.add_argument('--run-seconds', type=float, default=60)
        command.add_argument('--max-total-requests', type=int, default=522)
        command.add_argument('--max-seconds', type=float, default=900)
        command.add_argument('--timeout', type=float, default=25)
        command.add_argument('--num-predict', type=int, default=1024)
        command.add_argument('--num-ctx', type=int, default=8192)
        command.add_argument('--seed', type=int, default=20260928)
        command.add_argument('--temperature', type=float, default=0)
    summary = commands.add_parser('summarize', help='Summarize saved outcomes without model calls')
    summary.add_argument('directory', type=Path)
    for name, text in (('antigravity-check', 'Offline settings/context checks plus agy --version/--help; no model prompt'),
                       ('antigravity-smoke', 'Bounded Antigravity integration smoke; fixed authorized limits; not a benchmark')):
        command = commands.add_parser(name, help=text)
        command.add_argument('--executable', type=Path, required=True, help='Absolute path to the installed agy .exe')
        command.add_argument('--model', required=True)
        command.add_argument('--effort', choices=('low', 'medium', 'high'))
        command.add_argument('--prompt-transport', choices=('argv', 'stdin-stream-json'), default='argv')
        command.add_argument('--no-sandbox', action='store_true', help='Do not pass --sandbox (recorded as a weaker control)')
        command.add_argument('--settings', type=Path, help='Override the agy settings.json location to verify')
        command.add_argument('--account-credit-overages', choices=('never', 'always', 'unconfirmed'), default='unconfirmed',
            help='Your confirmation of the "AI Credit Overages" user setting (Plans page). Recorded as user confirmation, '
                 'never as machine verification; only "never" can pass the credit gate')
    commands.choices['antigravity-check'].add_argument('--list-models', action='store_true',
        help='Also run `agy models` (account-authenticated metadata, not a model prompt)')
    commands.choices['antigravity-smoke'].add_argument('--engine-source', type=Path, required=True)
    commands.choices['antigravity-smoke'].add_argument('--output', type=Path, default=Path('output/antigravity-smoke'))
    commands.choices['antigravity-smoke'].add_argument('--task', default='development-scheduling-100')
    credits = commands.add_parser('antigravity-disable-credits',
        help='Set useG1Credits to explicit false in agy settings.json (backup first; other settings preserved; never enables)')
    credits.add_argument('--settings', type=Path, help='Default: %%USERPROFILE%%\\.gemini\\antigravity-cli\\settings.json')
    args = parser.parse_args(argv)
    try:
        if args.command == 'antigravity-disable-credits':
            from .antigravity import default_settings_path, disable_g1_credits
            path = args.settings or default_settings_path()
            print(json.dumps(disable_g1_credits(path), indent=2, ensure_ascii=True))
            return 0
        if args.command in ('antigravity-check', 'antigravity-smoke'):
            from .antigravity import AntigravityConfig, readiness
            config = AntigravityConfig((str(args.executable.resolve()),), args.model, args.effort,
                prompt_transport=args.prompt_transport, sandbox=not args.no_sandbox,
                settings_path=str(args.settings) if args.settings else None,
                account_credit_overages=args.account_credit_overages)
            if args.command == 'antigravity-smoke':
                from .antigravity_smoke import run_smoke
                # Progress goes to stderr; the machine-readable result remains the only stdout output.
                data = run_smoke(args.engine_source, args.output, config, task_id=args.task,
                                 progress=lambda line: print(line, file=sys.stderr, flush=True))
            else:
                data = readiness(config, list_models=args.list_models)
            print(json.dumps(data, indent=2, ensure_ascii=True))
            return 0 if data.get('ready', data.get('status') == 'END_RUN_EXECUTED') else 1
        if args.command == 'discover-models':
            from .ollama import discover as discover_models
            data = discover_models(args.endpoint)
        elif args.command in ('preflight', 'develop', 'pilot'):
            from .ollama import OllamaConfig
            from .experiment import ExperimentConfig, run_experiment
            model = OllamaConfig(args.model, args.endpoint, args.timeout, temperature=args.temperature,
                                seed=args.seed, num_predict=args.num_predict, num_ctx=args.num_ctx)
            config = ExperimentConfig(args.engine_source, args.output, model,
                mode='development' if args.command == 'develop' else args.command,
                model_attempts=args.model_requests, development_check_attempts=args.check_attempts,
                run_deadline_seconds=args.run_seconds, max_total_requests=args.max_total_requests,
                max_duration_seconds=args.max_seconds)
            data = run_experiment(config)
        elif args.command == 'summarize':
            from .experiment import summarize_experiment
            data = summarize_experiment(args.directory)
        elif args.command == "demo":
            result = run_demo(args.engine_source, args.output)
            data = {"disclaimer": result["disclaimer"], "run_directory": result["normal"]["directory"],
                "engine_result": result["normal"]["engine_result"], "budget": result["normal"]["budget"],
                "normal_harness_stop_cause": result["normal"]["harness_stop_cause"],
                "final_candidate": result["normal"]["final_candidate"],
                "final_candidate_coverage": result["normal"]["final_candidate_coverage"],
                "evidence_coverage_history": result["normal"]["evidence_coverage"],
                "finalization": {key: result["normal"][key] for key in ("engine_execution", "trajectory_snapshot",
                    "trajectory_import", "journal_closure", "summary_persistence", "cleanup", "failures")},
                "exhaustion_directory": result["budget_exhaustion"]["directory"],
                "harness_stop_cause": result["budget_exhaustion"]["harness_stop_cause"],
                "exhausted_engine_result": result["budget_exhaustion"]["engine_result"],
                "interrupted_directory": result["interrupted_directory"], "recovery": result["recovery"]}
        elif args.command == "inspect":
            data = inspect_run(args.directory)
        else:
            data = close_interrupted(args.directory)
        print(json.dumps(data, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        parser.exit(1, json.dumps(diagnostic(exc), ensure_ascii=True) + "\n")
