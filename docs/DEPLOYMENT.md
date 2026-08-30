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

## Docker (Coming Soon)

```bash
docker build -t verdictai .
docker run -d \
  -p 8787:8787 \
  -e LLM_PROVIDER=openai_compatible \
  -e LLM_API_KEY=your-key \
  -e LLM_BASE_URL=https://api.example.com/v1 \
  -e LLM_MODEL=gpt-4o-mini \
  -v verdictai-data:/app/backend/data \
  verdictai
```

## Performance Notes

- **Mock mode**: Instant responses, no API costs
- **Step-explore**: ~2–5s per agent call, ~20s for critic (large input). Full 3-round debate: ~5–9 min
- **GPT-4o-mini**: ~1–3s per call. Full 3-round debate: ~2–4 min
- **Local Ollama (14B)**: ~5–15s per call depending on hardware

For best performance:
- Use `MAX_ROUNDS=2` for faster results (still multi-round)
- Use a fast model for `INTAKE_MODEL` (case preprocessing is one-shot)
- Ensure the server has ≥2GB RAM for PyMuPDF + LLM client
