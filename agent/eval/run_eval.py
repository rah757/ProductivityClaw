#!/usr/bin/env python3
"""
ProductivityClaw Eval Runner

Usage:
  python agent/eval/run_eval.py              # run all tests (skips LLM if Ollama is down)
  python agent/eval/run_eval.py --fast       # deterministic only, no LLM
  python agent/eval/run_eval.py --llm        # LLM integration tests only
  python agent/eval/run_eval.py --verbose     # verbose output
"""

import sys
import subprocess


def main():
    args = sys.argv[1:]
    cmd = ["python", "-m", "pytest", "agent/eval/test_suite.py", "-v", "--tb=short"]

    if "--fast" in args:
        cmd.extend(["-m", "not llm"])
        print("Running deterministic tests only (no LLM)...\n")
    elif "--llm" in args:
        cmd.extend(["-m", "llm"])
        print("Running LLM integration tests only...\n")
    else:
        print("Running all tests (LLM tests skipped if Ollama is not running)...\n")

    if "--verbose" in args:
        cmd.append("-s")  # show print output

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
