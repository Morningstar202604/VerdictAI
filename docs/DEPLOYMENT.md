# Deployment Guide

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock`, `openai`, `openai_compatible`, `ollama` |
| `LLM_API_KEY` | — | API key for the LLM provider |
| `LLM_BASE_URL` | — | Base URL (required for `openai_compatible`) |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for expert agents |
| `INTAKE_MODEL` | `gpt-4o-mini` | Model for case preprocessing & summarization |
| `MAX_ROUNDS` | `3` | Maximum debate rounds (2–10) |
| `HUMAN_IN_THE_LOOP` | `false` | Enable human judge review |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Model name for Ollama provider |
| `ACCESS_PASSWORD` | — | When set, all pages/API/WebSocket require login (intranet gate) |
| `JUDGE_MODE` | `ai` | `ai` or `human` (HITL) |
| `HITL_TIMEOUT` | `300` | Seconds to wait for the human verdict; auto-adopts the AI draft on timeout (0 = unlimited) |
| `MEMORY_ROUNDS` | `2` | Round summaries injected into expert context |
| `CONTEXT_CHAR_LIMIT` | `12000` | Max characters per LLM call (0 = unlimited) |
| `MAX_CONCURRENCY` | `4` | Parallel expert cap per round |
| `LLM_TIMEOUT` | `180` | Per-call timeout in seconds (0 = unlimited) |
| `LLM_MAX_TOKENS` | `0` | Max output tokens per call (reasoning-chain models truncate JSON if too low; 4000–8000 recommended) |
| `WEB_SEARCH_ENABLED` | `true` | Enable the Bing-CN web search tool |

## One-Command Start / Stop

```bash
python tools/start_all.py       # backend (8787) + local engine (9100), windowless daemons with auto-restart
python tools/start_all.py stop
```

A bundled **local reasoning engine** (`backend/ai_engine/`, port 9100) runs the entire pipeline offline — point `LLM_BASE_URL` at `http://127.0.0.1:9100/v1` (the default `tools/start_all.py` setup) or swap in any cloud API.

## Manual Deployment

### 1. Clone & Install

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys and preferences
```

### 3. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

### 4. (Optional) Process Manager

For production, use a process manager:

```bash
# Using nohup
nohup uvicorn app.main:app --host 0.0.0.0 --port 8787 &

# Using systemd (Linux)
# See verdictai.service below
```

## systemd Service

```ini
# /etc/systemd/system/verdictai.service
[Unit]
Description=VerdictAI Multi-Agent Debate System
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/VerdictAI/backend
ExecStart=/opt/VerdictAI/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8787
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable verdictai
sudo systemctl start verdictai
```

## Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name verdict.example.com;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

## Docker Deployment

Two services, orchestrated by `docker-compose.yml` at the repo root:

| Service | Image | Exposed Port | Purpose |
|---|---|---|---|
| `backend` | `backend/Dockerfile` (python:3.11-slim) | `8787` | FastAPI app + built-in UI + static assets |
| `frontend` | `frontend/Dockerfile` (node:20 → nginx:1.27) | `8080` | React build served by nginx, reverses `/api` `/ws` `/static` `/sandbox` to backend |

The backend image installs `fonts-noto-cjk` so matplotlib charts render Chinese correctly.

### 1. Quick Start

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI

cp backend/.env.example backend/.env      # fill in LLM_API_KEY etc.
docker compose up -d --build
```

Then open:
- **React frontend**: http://<server>:8080
- **Backend built-in UI**: http://<server>:8787

Persistent data (case library, debate records, generated charts) lives in `./backend/data`, mounted into the container at `/app/data`.

### 2. Manage

```bash
docker compose ps            # status
docker compose logs -f backend
docker compose restart backend
docker compose down          # stop (data persists in ./backend/data)
```

### 3. Upgrade

```bash
git pull
docker compose up -d --build
```

### 4. Notes

- **API keys never enter the image**: `env_file: ./backend/.env` is injected at runtime; `.env` is git- and docker-ignored.
- **Single backend worker by design**: debate sessions are in-process state; keep 1 replica unless you add a shared store.
- **CORS**: the React frontend is same-origin through nginx, so no extra CORS config is needed.

## Performance Notes

- **Mock mode**: Instant responses, no API costs
- **Step-explore**: ~2–5s per agent call, ~20s for critic (large input). Full 3-round debate: ~5–9 min
- **GPT-4o-mini**: ~1–3s per call. Full 3-round debate: ~2–4 min
- **Local Ollama (14B)**: ~5–15s per call depending on hardware

For best performance:
- Use `MAX_ROUNDS=2` for faster results (still multi-round)
- Use a fast model for `INTAKE_MODEL` (case preprocessing is one-shot)
- Ensure the server has ≥2GB RAM for PyMuPDF + LLM client
