"""The ``tiresias`` command line.

    tiresias check     --config tiresias.yml   static check against the dbt artifacts
    tiresias calibrate --config tiresias.yml   grounding scores for picking the threshold
    tiresias eval      --config tiresias.yml   retrieval recall@k, then the live gold set
    tiresias mcp       --config tiresias.yml   stdio MCP server (e.g. for Claude Code)

Exit codes: 0 success, 1 a check or eval failed, 2 the command could not run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from tiresias.agent import TiresiasAgent
from tiresias.check import check_config
from tiresias.config import TiresiasConfig, load_config
from tiresias.evals import (
    calibration_report,
    load_gold,
    load_retrieval_gold,
    retrieval_recall,
    run_gold,
)
from tiresias.mcp_server import serve_stdio
from tiresias.retrieval import FastEmbedEmbedder, Retriever

logger = logging.getLogger(__name__)


def _retriever(config: TiresiasConfig) -> Retriever:
    return Retriever.from_config(config, embedder=FastEmbedEmbedder())


def _make_agent(config: TiresiasConfig, retriever: Retriever) -> TiresiasAgent:
    return TiresiasAgent(config, retriever=retriever)


def _check(config: TiresiasConfig) -> int:
    problems = check_config(config)
    if not problems:
        print(f"{config.city}: no problems found")
        return 0
    for problem in problems:
        print(f"{problem.severity.upper():8} {problem.message}")
    errors = sum(p.severity == "error" for p in problems)
    print(f"\n{errors} error(s), {len(problems) - errors} warning(s)")
    return 1 if errors else 0


def _calibrate(config: TiresiasConfig) -> int:
    if config.gold.answers is None:
        print("no answer gold set configured (gold.answers)", file=sys.stderr)
        return 2
    report = calibration_report(_retriever(config), load_gold(config.gold.answers), config)
    print(report.to_text())
    return 0


def _eval(config: TiresiasConfig, retrieval_only: bool) -> int:
    retriever = _retriever(config)
    if retrieval_only and config.gold.retrieval is None:
        print("no retrieval gold set configured (gold.retrieval)", file=sys.stderr)
        return 2
    ok = True
    if config.gold.retrieval is not None:
        report = retrieval_recall(retriever, load_retrieval_gold(config.gold.retrieval))
        print(f"retrieval recall@{report.k} = {report.recall:.2f} (floor {report.min_recall:.2f})")
        for query in report.misses:
            print(f"  MISS {query}")
        ok = report.passed
    if retrieval_only:
        return 0 if ok else 1

    if config.gold.answers is None:
        print("no answer gold set configured (gold.answers)", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set; the gold eval calls the model. "
            "Use --retrieval-only to skip it.",
            file=sys.stderr,
        )
        return 2
    cases = load_gold(config.gold.answers)
    results = asyncio.run(run_gold(_make_agent(config, retriever), cases))
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.id}" + (f": {result.reason}" if result.reason else ""))
    passed = sum(r.passed for r in results)
    print(f"\ngold: {passed}/{len(results)} passed")
    return 0 if ok and passed == len(results) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tiresias", description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("check", "check tiresias.yml against the dbt artifacts"),
        ("calibrate", "print grounding scores for the gold questions"),
        ("eval", "run retrieval recall@k and the live gold set"),
        ("mcp", "serve the warehouse over stdio MCP"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument(
            "--config", type=Path, default=Path("tiresias.yml"), help="path to tiresias.yml"
        )
        if name == "eval":
            sub.add_argument("--retrieval-only", action="store_true", help="skip the live gold set")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # MCP speaks over stdout, so logs always go to stderr.
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, stream=sys.stderr)
    try:
        config = load_config(args.config)
        if args.command == "check":
            return _check(config)
        if args.command == "calibrate":
            return _calibrate(config)
        if args.command == "eval":
            return _eval(config, args.retrieval_only)
        serve_stdio(config)
        return 0
    except Exception:
        # The command could not run (bad config, missing artifacts, ...): show the
        # full traceback, but exit 2 so CI can tell it apart from a failed check.
        logger.exception("tiresias %s could not run", args.command)
        return 2


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
