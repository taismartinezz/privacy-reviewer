"""Turn a Review into a GitHub PR comment."""

from __future__ import annotations

from .agent import Review

MARKER = "<!-- privacy-reviewer -->"
ICONS = {"high": "🔴", "medium": "🟠", "low": "🟡"}
ORDER = ["high", "medium", "low"]


def render_comment(review: Review, model: str) -> str:
    lines = [MARKER, "## 🔒 Privacy review", "", review.summary.strip() or "_No summary._", ""]

    if not review.findings:
        lines.append("✅ No privacy issues found in this PR.")
    else:
        counts = {s: sum(1 for f in review.findings if f.get("severity") == s) for s in ORDER}
        lines.append(" · ".join(f"{ICONS[s]} {counts[s]} {s}" for s in ORDER if counts[s]))
        lines.append("")
        for sev in ORDER:
            for f in (f for f in review.findings if f.get("severity") == sev):
                loc = f"`{f.get('file', '?')}`" + (f" line {f['line']}" if f.get("line") else "")
                lines += [
                    f"### {ICONS[sev]} {f.get('title', 'Untitled')}",
                    f"**{sev}** · {f.get('category', 'other')} · {loc}",
                    "",
                    f.get("explanation", "").strip(),
                    "",
                    f"**Suggested fix:** {f.get('suggestion', '').strip()}",
                    "",
                ]

    if review.tool_calls:
        lines += [
            "<details><summary>What the reviewer checked</summary>",
            "",
            *[f"- `{c}`" for c in review.tool_calls],
            "",
            "</details>",
            "",
        ]
    lines.append(
        f"<sub>Automated review by an LLM agent ({model}, {review.turns} turns). "
        "It can miss things or be wrong; treat it as a second pair of eyes, not a sign-off.</sub>"
    )
    return "\n".join(lines)
