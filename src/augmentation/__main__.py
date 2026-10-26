"""Command-line entry point for extraction, generation and isolated execution."""
import argparse
import json
from pathlib import Path

from .execution import execute
from .pipeline import build_request, generate, prepare, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    extract = commands.add_parser("prepare", help="Analyze a completed repository without running its code")
    extract.add_argument("--repository", type=Path, required=True)
    extract.add_argument("--patch", type=Path, required=True)
    extract.add_argument("--issue", type=Path, required=True)
    extract.add_argument("--trajectory", type=Path)
    extract.add_argument("--base-repository", type=Path)
    extract.add_argument("--max-depth", type=int, default=6)
    extract.add_argument("--max-order", type=int, default=3)
    extract.add_argument("--max-regions", type=int, default=80)
    extract.add_argument("--analysis-mode", choices=["joint", "legacy"], default="joint")
    extract.add_argument("--output", type=Path, required=True)
    model = commands.add_parser("generate", help="Use the configured DeepSeek provider")
    model.add_argument("--prepared", type=Path, required=True)
    model.add_argument("--candidate", action="append")
    model.add_argument("--output", type=Path, required=True)
    request = commands.add_parser("request", help="Write one model request without sending it")
    request.add_argument("--prepared", type=Path, required=True)
    request.add_argument("--candidate", required=True)
    request.add_argument("--output", type=Path, required=True)
    agent = commands.add_parser("agent", help="Inspect evidence and augment tests within an explicit total budget")
    agent.add_argument("--prepared", type=Path, required=True)
    agent.add_argument("--candidate", action="append")
    agent.add_argument("--command", help="Caller-selected JSON argv; omit for generation without execution")
    agent.add_argument("--max-rounds", type=int, default=3)
    agent.add_argument("--max-feedback-rounds", type=int, default=2,
                       help="Calls reserved for review and repair after the first augmentation")
    agent.add_argument("--max-executions", type=int, default=2)
    agent.add_argument("--max-candidates", type=int, default=8)
    agent.add_argument("--token-budget", type=int, default=100000)
    agent.add_argument("--max-output-tokens", type=int, default=8192)
    agent.add_argument("--timeout", type=float, default=300)
    agent.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("execute", help="Run a decoded response in an isolated repository copy")
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--response", type=Path, required=True)
    run.add_argument("--command", required=True, help='JSON argv, e.g. ["python3","-m","pytest","{test_paths}"]')
    run.add_argument("--timeout", type=float, default=300)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        if args.output.exists():
            parser.error("output already exists")
        result = prepare(args.repository, args.patch.read_text(), args.issue.read_text(),
                         json.loads(args.trajectory.read_text()) if args.trajectory else None,
                         base_repository=args.base_repository, max_depth=args.max_depth,
                         max_order=args.max_order, max_regions=args.max_regions, analysis_mode=args.analysis_mode)
        write_json(args.output, result)
        print(json.dumps(result["counts"]))
    elif args.action == "request":
        if args.output.exists():
            parser.error("output already exists")
        write_json(args.output, build_request(json.loads(args.prepared.read_text()), args.candidate))
        print(json.dumps({"request": str(args.output), "external_model_calls": 0}))
    elif args.action == "generate":
        results = generate(json.loads(args.prepared.read_text()), args.output, candidate_ids=args.candidate)
        print(json.dumps({"requests": len(results), "decoded": sum(r["status"] == "decoded" for r in results)}))
    elif args.action == "agent":
        from .agent import run_agent
        result = run_agent(json.loads(args.prepared.read_text()), args.output, candidate_ids=args.candidate,
                           command=json.loads(args.command) if args.command else None, max_rounds=args.max_rounds,
                           max_executions=args.max_executions, max_candidates=args.max_candidates,
                           max_feedback_rounds=args.max_feedback_rounds,
                           token_budget=args.token_budget, max_output_tokens=args.max_output_tokens, timeout=args.timeout)
        print(json.dumps({"candidates": len(result["results"]), "external_model_calls": result["external_model_calls"],
                          "charged_tokens": result["charged_tokens"], "generated_proposals": result["generated_proposals"]}))
    else:
        response = json.loads(args.response.read_text())
        result = execute(json.loads(args.prepared.read_text()), response.get("response", response),
                         args.output, json.loads(args.command), timeout=args.timeout)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
