"""Command-line entry point.

In GitHub Actions:   python -m privacy_reviewer --pr 42
Locally on a diff:   python -m privacy_reviewer --diff-file my.diff --repo-root ../canopy
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import run_review
from .report import render_comment
from .tools import RepoTools

DEFAULT_MODEL = "claude-sonnet-5-5"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="privacy_reviewer", description="LLM agent that reviews PRs for privacy risks.")
    ap.add_argument("--pr", type=int, help="Pull request number (uses GITHUB_TOKEN and GITHUB_REPOSITORY).")
    ap.add_argument("--diff-file", help="Review a local diff file instead of a PR.")
    ap.add_argument("--repo-root", default=".", help="Checked-out repository the agent may read.")
    ap.add_argument("--model", default=os.environ.get("PRIVACY_REVIEWER_MODEL", DEFAULT_MODEL))
    ap.add_argument("--max-turns", type=int, default=10)
    ap.add_argument("--fail-on", choices=["high", "medium", "low", "never"], default="never",
                    help="Exit non-zero if a finding at or above this severity is found.")
    ap.add_argument("--json", action="store_true", help="Print the raw review as JSON.")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; skipping privacy review.", file=sys.stderr)
        return 0

    import anthropic  # imported late so --help works without the SDK installed

    client = anthropic.Anthropic()
    tools = RepoTools(args.repo_root)

    gh = None
    if args.diff_file:
        with open(args.diff_file) as f:
            diff = f.read()
        title, body = os.path.basename(args.diff_file), ""
    elif args.pr:
        from .github import GitHub

        gh = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
        pr = gh.get_pr(args.pr)
        title, body, diff = pr["title"], pr.get("body") or "", gh.get_diff(args.pr)
    else:
        ap.error("pass --pr or --diff-file")

    review = run_review(client, args.model, tools, title, body, diff, max_turns=args.max_turns)
    comment = render_comment(review, args.model)

    if args.json:
        print(json.dumps({"summary": review.summary, "findings": review.findings, "tool_calls": review.tool_calls}, indent=2))
    else:
        print(comment)

    if gh is not None:
        gh.upsert_comment(args.pr, comment)

    levels = {"low": 1, "medium": 2, "high": 3}
    if args.fail_on != "never" and review.worst_severity:
        if levels[review.worst_severity] >= levels[args.fail_on]:
            print(f"Failing: found a {review.worst_severity}-severity privacy issue.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
