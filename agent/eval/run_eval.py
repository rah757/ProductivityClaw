#!/usr/bin/env python3
"""
ProductivityClaw Eval Runner

Usage:
  python agent/eval/run_eval.py              # run all tests (skips LLM/deepeval if unavailable)
  python agent/eval/run_eval.py --fast       # deterministic only, no LLM
  python agent/eval/run_eval.py --llm        # LLM integration tests only (needs MLX server)
  python agent/eval/run_eval.py --deepeval   # DeepEval quality metrics only (needs MLX server)
  python agent/eval/run_eval.py --verbose    # verbose output
"""

import sys
import subprocess


TEST_FILES = [
    "agent/eval/test_suite.py",
    "agent/eval/test_write_tools.py",
    "agent/eval/test_deepeval.py",
]


def main():
    args = sys.argv[1:]
    cmd = ["python", "-m", "pytest"] + TEST_FILES + ["-v", "--tb=short"]

    if "--fast" in args:
        cmd.extend(["-m", "not llm and not deepeval"])
        print("Running deterministic tests only (no LLM, no DeepEval)...\n")
    elif "--llm" in args:
        cmd.extend(["-m", "llm"])
        print("Running LLM integration tests only (requires MLX server)...\n")
    elif "--deepeval" in args:
        cmd.extend(["-m", "deepeval"])
        print("Running DeepEval quality metrics only (requires MLX server)...\n")
    else:
        print("Running all tests (LLM/DeepEval tests skipped if unavailable)...\n")

    if "--verbose" in args:
        cmd.append("-s")

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
