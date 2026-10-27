"""Run the agent on eval/questions.yaml and write eval/results.md.

    python -m eval.run_eval                 # all cases once
    python -m eval.run_eval --repeat 3      # each case 3 times (measures flakiness)
    python -m eval.run_eval --only refund_cw1002_half --delay 4
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from eval.checks import check_case, policy_numbers
from helpdesk.agent import Agent
from helpdesk.llm import OpenAICompatibleModel

EVAL_DIR = Path(__file__).resolve().parent


def ask_with_retry(agent: Agent, question: str, retries: int = 4):
    """Free tiers have tight rate limits; wait and retry on HTTP 429."""
    for attempt in range(retries + 1):
        history_length = len(agent.messages)
        try:
            return agent.ask(question)
        except Exception as exc:
            rate_limited = "429" in str(exc) or "ratelimit" in type(exc).__name__.lower()
            if not rate_limited or attempt == retries:
                raise
            # Roll the conversation back to before this question, so the
            # retry doesn't send it (or half a tool exchange) twice.
            del agent.messages[history_length:]
            wait = 15 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s ...", flush=True)
            time.sleep(wait)


def run_case(model, case: dict, known_numbers: set[float], delay: float) -> dict:
    agent = Agent(model)
    questions = case.get("turns") or [case["question"]]
    all_results: list[dict] = []
    result = None
    try:
        for q in questions:
            result = ask_with_retry(agent, q)
            all_results.extend(c.result for c in result.tool_calls)
            time.sleep(delay)
    except Exception as exc:
        return {"id": case["id"], "passed": False, "failures": [f"error: {type(exc).__name__}: {exc}"],
                "tools": [], "answer": ""}

    tools = [c.name for c in result.tool_calls]
    outcome = check_case(case, result.answer, tools, all_results, questions, known_numbers)
    return {"id": case["id"], "passed": outcome.passed, "failures": outcome.failures,
            "tools": tools, "answer": result.answer, "steps": result.steps}


def write_report(runs: list[list[dict]], cases: list[dict], model_name: str, path: Path) -> None:
    repeat = len(runs)
    passed_per_run = [sum(r["passed"] for r in run) for run in runs]
    lines = [
        "# Evaluation results",
        "",
        f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- Model: `{model_name}`",
        f"- Cases: {len(cases)}, runs: {repeat}",
        f"- **Passed: {' / '.join(str(p) for p in passed_per_run)} of {len(cases)}**"
        + (" (per run)" if repeat > 1 else ""),
        "",
        "| Case | Result | Tools called | Failed checks |",
        "| --- | --- | --- | --- |",
    ]
    for i, case in enumerate(cases):
        results = [run[i] for run in runs]
        ok = sum(r["passed"] for r in results)
        status = "PASS" if ok == repeat else ("FAIL" if ok == 0 else f"FLAKY {ok}/{repeat}")
        fails = "; ".join(sorted({f for r in results for f in r["failures"]})) or "-"
        tools = ", ".join(results[-1]["tools"]) or "-"
        lines.append(f"| `{case['id']}` | {status} | {tools} | {fails} |")

    lines += ["", "## Answers (last run)", ""]
    for case, r in zip(cases, runs[-1]):
        question = " / ".join(case.get("turns") or [case["question"]])
        answer = r["answer"].replace("\n", " ") or "(no answer)"
        lines += [f"**{case['id']}** {'PASS' if r['passed'] else 'FAIL'}", f"> Q: {question}", f">", f"> A: {answer}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", nargs="*", help="Case ids to run")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between model calls (rate limits)")
    parser.add_argument("--out", default=str(EVAL_DIR / "results.md"))
    args = parser.parse_args()

    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    model = OpenAICompatibleModel.from_env()
    known = policy_numbers()

    runs = []
    for n in range(args.repeat):
        run = []
        for case in cases:
            r = run_case(model, case, known, args.delay)
            print(f"[run {n + 1}] {'PASS' if r['passed'] else 'FAIL'} {case['id']} {r['failures'] or ''}", flush=True)
            run.append(r)
        runs.append(run)

    write_report(runs, cases, model.model, Path(args.out))
    Path(args.out).with_suffix(".json").write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nPassed {sum(r['passed'] for r in runs[-1])}/{len(cases)} (last run). Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
