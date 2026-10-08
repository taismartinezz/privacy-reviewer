"""Minimal GitHub REST helpers: fetch the PR, fetch its diff, post or update one comment."""

from __future__ import annotations

import requests

from .report import MARKER

API = "https://api.github.com"


class GitHub:
    def __init__(self, token: str, repo: str):
        self.repo = repo
        self.s = requests.Session()
        self.s.headers.update(
            {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
        )

    def get_pr(self, number: int) -> dict:
        r = self.s.get(f"{API}/repos/{self.repo}/pulls/{number}", headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        return r.json()

    def get_diff(self, number: int) -> str:
        r = self.s.get(f"{API}/repos/{self.repo}/pulls/{number}", headers={"Accept": "application/vnd.github.diff"})
        r.raise_for_status()
        return r.text

    def upsert_comment(self, number: int, body: str) -> None:
        """Update our previous comment if there is one, so re-runs don't spam the PR."""
        url = f"{API}/repos/{self.repo}/issues/{number}/comments"
        page = 1
        while True:
            r = self.s.get(url, params={"per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            for c in batch:
                if MARKER in (c.get("body") or ""):
                    self.s.patch(f"{API}/repos/{self.repo}/issues/comments/{c['id']}", json={"body": body}).raise_for_status()
                    return
            if len(batch) < 100:
                break
            page += 1
        self.s.post(url, json={"body": body}).raise_for_status()
