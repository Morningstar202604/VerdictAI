# Contributing to VerdictAI

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

- Python: Follow PEP 8. Use `ruff` for linting.
- Frontend: Vanilla JS, no build step required.
- Run `ruff check app/` before committing.

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
