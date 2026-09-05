# Contributing to VerdictAI

## Working rules for this repository

* Dependency updates: search the whole repository for every occurrence of a dependency (build files, lockfiles, CI workflows, docs) before bumping. A partial bump — declaration updated but the lockfile or a pinned action left behind — is the most common cause of "works locally, CI fails". Keep lockfiles in the same commit as the declaration. Move version-coupled toolchain upgrades (e.g. Gradle/AGP/Kotlin/Hilt or the Python/uv pair) together in one commit.
* Refactoring: pull latest main first, work on a fresh branch, keep commits atomic with messages that state the why, and always run the full check suite before pushing (for this repo: `pytest` for the backend and `npm run build` for the frontend). A branch left behind main cannot be merged under the repository's branch protection.
* Merge conflicts: resolve conflicts in the working tree against the latest main; never force-push shared branches; never resolve a conflict by blindly taking either side — re-read both sides and keep both changes when they are both valid.
* Versioning: releases follow X.Y.Z starting at 0.0.0. Last digit = fixes, middle digit = feature work, first digit stays 0 until a stable release is declared. Bump the version in code, CHANGELOG.md and the tag in the same change.

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend

python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run in mock mode (no API key needed)
uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

Open `http://localhost:8787` to test.

## Code Style

- Python: Follow PEP 8. `ruff` (baseline config: `backend/ruff.toml`) and `pytest` (tests: `backend/tests/`) run in CI; dev-only dependencies live in `backend/requirements-dev.txt`.
- Frontend: two deliverables — the built-in single-file UI `backend/app/static/index.html` (vanilla JS, no build step; CI syntax-checks it) and the React/Vite app in `frontend/` (`npm run build`, also run by CI).
- Run `ruff check app/` and `pytest` from `backend/` before committing.

## Project Layout

- `app/agents/` — Expert roles, tools, and LangGraph nodes
- `app/graph/` — StateGraph definition and debate orchestration
- `app/intake/` — PDF processing and case structuring
- `app/models/` — LLM abstraction and state definitions
- `app/static/` — Frontend (single HTML file)
- `app/ws/` — WebSocket manager

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-change`
3. Commit with a clear message
4. Push and open a Pull Request

## Reporting Issues

Open an issue on GitHub with:
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, LLM provider)
