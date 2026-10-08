# Privacy Reviewer

An LLM agent that reviews every pull request for **privacy and security risks** and leaves one comment on the PR explaining what it found and how to fix it.

I build apps that handle sensitive data: [Canopy](https://github.com/taismartinezz/canopy) stores research staff's wellbeing journals, and [Che](https://github.com/taismartinezz/che) handles people's contact details. Normal code review catches bugs, but privacy problems are easy to miss because the code *works*. This agent is a second reviewer that only cares about one question: **could this change expose someone's private data?**

## Why I built it

Canopy encrypts journal entries before saving them. But it turned out that **drafts** were saved unencrypted in `localStorage` under a fixed key and weren't cleared on sign-out. On a shared lab computer, one person's unfinished entry could load into the next person's editor. The code passed review and tests because nothing was broken; it just leaked.

That bug is the kind of thing this agent is built to catch, and it's the test case in [`tests/fixtures`](tests/fixtures).

## How it works

```
PR opened / updated
        │
        ▼
 GitHub Action checks out the PR and fetches the diff
        │   (lockfiles, images and build output are filtered out)
        ▼
 ┌──────────────── agent loop (max 10 turns) ────────────────┐
 │  Claude reads the diff and decides what to check          │
 │     ├─ search_code("canopy_journal_draft|signOut")        │
 │     ├─ read_file("src/components/AppShell.tsx")           │
 │     └─ ... until it has evidence                          │
 │  submit_review({ summary, findings[] })                   │
 └───────────────────────────────────────────────────────────┘
        │
        ▼
 One PR comment (updated in place on re-runs), optional failing check
```

The important design choice is that the agent **investigates before it accuses**. A diff alone can't tell you whether a key is cleared on sign-out or whether a table has row-level security, so the model gets two read-only tools to check the rest of the repo, and the prompt tells it to only report issues it can tie to specific code.

It looks for:

| Category | Example |
|---|---|
| `plaintext-storage` | Sensitive data in `localStorage`, cookies, logs, or unencrypted columns |
| `access-control` | Weakened RLS, missing server-side role checks, trusting client-sent IDs |
| `data-exposure` | Data shown to the wrong user, cached across users, not cleared on sign-out |
| `oauth-scope` | New or broader OAuth scopes than the feature needs |
| `logging` | Personal data in console logs or analytics |
| `third-party` | Personal data sent to external APIs (including LLM APIs) |
| `secrets` | Service-role keys or API keys exposed to the client |

## Use it on a repo

1. Copy [`examples/privacy-review.yml`](examples/privacy-review.yml) to `.github/workflows/privacy-review.yml` in your repo.
2. Add an `ANTHROPIC_API_KEY` secret under **Settings → Secrets and variables → Actions**.
3. Open a PR.

If the key isn't set, the action skips quietly instead of failing. Set `fail-on: high` to block merges on serious findings.

## Run it locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
git -C ../canopy diff main > my.diff
python -m privacy_reviewer --diff-file my.diff --repo-root ../canopy
```

## Safety choices

- **Read-only tools, confined to the repo.** The agent can read and search files; it can't write, run code, or reach the network. Paths that escape the repo root are rejected.
- **Untrusted input.** The diff and repo contents are treated as data, and the prompt tells the model never to follow instructions inside them.
- **Bounded.** A turn limit forces a final answer, and diffs and file reads are size-capped.
- **No secrets for forks.** The workflow uses `pull_request`, so PRs from forks don't get the API key.
- **One comment, not spam.** Re-runs update the same comment.

## Limitations

It's an LLM: it can miss issues or flag things that are fine, so it's a second pair of eyes, not a sign-off. It only sees the PR's code, not your database's live policies or environment settings.

## Tests

```bash
pip install pytest && pytest -q
```

Tests replace the model with a scripted fake, so they run without an API key. They cover the tool sandbox, diff filtering, the agent loop (investigate → submit, forced submit on the last turn, nudging when the model replies in prose), the PR comment, and the CLI.

## Built with

Python, the [Anthropic API](https://docs.claude.com) (tool use), GitHub Actions. I designed the review rubric and safety choices and built it with AI coding tools.
