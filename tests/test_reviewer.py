"""Tests run without network or an API key: the LLM is replaced by a scripted fake."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from privacy_reviewer.__main__ import main
from privacy_reviewer.agent import filter_diff, run_review
from privacy_reviewer.report import MARKER, render_comment
from privacy_reviewer.tools import RepoTools

FIXTURES = Path(__file__).parent / "fixtures"
REPO = FIXTURES / "sample_repo"
DIFF = (FIXTURES / "drafts_bug.diff").read_text()

DRAFT_FINDING = {
    "severity": "high",
    "category": "data-exposure",
    "file": "src/app/journal/page.tsx",
    "line": 5,
    "title": "Journal drafts persist across users",
    "explanation": "Drafts are stored in plaintext under a fixed key and not cleared on sign-out.",
    "suggestion": "Scope the key per user, clear it on sign-out, and encrypt the draft.",
}


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


class FakeClient:
    """Plays back a fixed list of model responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot: the agent keeps appending to the same messages list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return SimpleNamespace(content=self.responses.pop(0))


# ---- tools ---------------------------------------------------------------

def test_read_file_returns_numbered_lines():
    out = RepoTools(REPO).read_file("src/app/journal/page.tsx", 1, 2)
    assert out.splitlines()[0] == '1: const DRAFT_KEY = "canopy_journal_draft";'


def test_read_file_blocks_path_escape():
    assert "escapes the repository" in RepoTools(REPO).read_file("../../drafts_bug.diff")


def test_search_finds_key_but_not_in_sign_out():
    tools = RepoTools(REPO)
    hits = tools.search_code("canopy_journal_draft|removeItem")
    assert "page.tsx" in hits and "AppShell" not in hits


def test_search_rejects_bad_regex():
    assert "invalid regex" in RepoTools(REPO).search_code("(")


# ---- diff filtering ------------------------------------------------------

def test_filter_diff_drops_lockfiles():
    out = filter_diff(DIFF)
    assert "page.tsx" in out and "package-lock.json" not in out


# ---- agent loop ----------------------------------------------------------

def test_agent_investigates_then_submits():
    client = FakeClient([
        [tool_use("t1", "search_code", {"pattern": "canopy_journal_draft|signOut"})],
        [tool_use("t2", "submit_review", {"summary": "Adds journal drafts.", "findings": [DRAFT_FINDING]})],
    ])
    review = run_review(client, "test-model", RepoTools(REPO), "Add drafts", "", DIFF)

    assert review.turns == 2
    assert review.worst_severity == "high"
    assert review.tool_calls == ["search_code(pattern='canopy_journal_draft|signOut')"]
    # The real search result was sent back to the model.
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and "AppShell.tsx" in tool_result["content"]
    # Lockfile was filtered out of what the model saw.
    assert "package-lock.json" not in client.requests[0]["messages"][0]["content"]


def test_agent_is_forced_to_submit_on_last_turn():
    looping = [[tool_use(f"t{i}", "read_file", {"path": "src/app/journal/page.tsx"})] for i in range(2)]
    final = [[tool_use("tf", "submit_review", {"summary": "ok", "findings": []})]]
    client = FakeClient(looping + final)
    review = run_review(client, "m", RepoTools(REPO), "t", "", DIFF, max_turns=3)

    assert client.requests[-1]["tool_choice"] == {"type": "tool", "name": "submit_review"}
    assert client.requests[0]["tool_choice"] == {"type": "auto"}
    assert review.findings == [] and review.turns == 3


def test_agent_nudges_when_model_replies_in_prose():
    client = FakeClient([
        [SimpleNamespace(type="text", text="Looks fine to me.")],
        [tool_use("t1", "submit_review", {"summary": "fine", "findings": []})],
    ])
    review = run_review(client, "m", RepoTools(REPO), "t", "", DIFF)
    assert review.turns == 2
    assert "submit_review" in client.requests[1]["messages"][-1]["content"]


# ---- report --------------------------------------------------------------

def test_comment_has_marker_and_finding():
    client = FakeClient([[tool_use("t", "submit_review", {"summary": "s", "findings": [DRAFT_FINDING]})]])
    review = run_review(client, "m", RepoTools(REPO), "t", "", DIFF)
    body = render_comment(review, "m")
    assert body.startswith(MARKER)
    assert "🔴 1 high" in body and "Journal drafts persist across users" in body
    assert "`src/app/journal/page.tsx` line 5" in body


def test_comment_when_clean():
    client = FakeClient([[tool_use("t", "submit_review", {"summary": "No data changes.", "findings": []})]])
    body = render_comment(run_review(client, "m", RepoTools(REPO), "t", "", DIFF), "m")
    assert "No privacy issues found" in body


# ---- CLI -----------------------------------------------------------------

def test_cli_skips_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--diff-file", str(FIXTURES / "drafts_bug.diff")]) == 0
    assert "skipping" in capsys.readouterr().err


def test_cli_fail_on_high(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = FakeClient([[tool_use("t", "submit_review", {"summary": "s", "findings": [DRAFT_FINDING]})]])
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake)
    code = main(["--diff-file", str(FIXTURES / "drafts_bug.diff"), "--repo-root", str(REPO), "--fail-on", "high"])
    assert code == 1
