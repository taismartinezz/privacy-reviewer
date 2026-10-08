"""The agent loop: the model reads the diff, investigates with tools, then submits a review."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .prompt import SYSTEM_PROMPT, build_user_message
from .tools import TOOL_SCHEMAS, RepoTools

MAX_DIFF_CHARS = 60_000
SKIP_FILE_PATTERNS = [
    r"(^|/)package-lock\.json$",
    r"(^|/)yarn\.lock$",
    r"(^|/)pnpm-lock\.yaml$",
    r"\.(png|jpe?g|gif|svg|ico|pdf|woff2?)$",
    r"(^|/)dist/",
    r"\.min\.(js|css)$",
]


@dataclass
class Review:
    summary: str
    findings: list[dict]
    tool_calls: list[str] = field(default_factory=list)
    turns: int = 0

    @property
    def worst_severity(self) -> str | None:
        order = {"high": 3, "medium": 2, "low": 1}
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: order.get(f.get("severity"), 0))["severity"]


def filter_diff(diff: str) -> str:
    """Drop lockfiles, binaries and build output, then cap the size."""
    chunks = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    kept = []
    for chunk in chunks:
        m = re.match(r"diff --git a/(\S+) b/(\S+)", chunk)
        if m and any(re.search(p, m.group(2)) for p in SKIP_FILE_PATTERNS):
            continue
        kept.append(chunk)
    out = "".join(kept)
    if len(out) > MAX_DIFF_CHARS:
        out = out[:MAX_DIFF_CHARS] + "\n... [diff truncated; use read_file to inspect remaining files]"
    return out


def run_review(
    client,
    model: str,
    tools: RepoTools,
    title: str,
    body: str,
    diff: str,
    max_turns: int = 10,
) -> Review:
    messages = [{"role": "user", "content": build_user_message(title, body, filter_diff(diff))}]
    calls: list[str] = []

    for turn in range(1, max_turns + 1):
        last_turn = turn == max_turns
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            # On the last turn, force a final answer so the loop always ends with a review.
            tool_choice={"type": "tool", "name": "submit_review"} if last_turn else {"type": "auto"},
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        for block in tool_uses:
            if block.name == "submit_review":
                return Review(
                    summary=block.input.get("summary", ""),
                    findings=block.input.get("findings", []),
                    tool_calls=calls,
                    turns=turn,
                )

        if not tool_uses:
            # The model answered in prose instead of submitting; ask it to submit.
            messages.append({"role": "user", "content": "Please call submit_review with your findings."})
            continue

        results = []
        for block in tool_uses:
            calls.append(f"{block.name}({_short(block.input)})")
            output = tools.run(block.name, dict(block.input))
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})

    return Review(summary="The reviewer did not finish.", findings=[], tool_calls=calls, turns=max_turns)


def _short(args: dict) -> str:
    s = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return s if len(s) < 80 else s[:77] + "..."
