<p align="center">
  <img src="backend/data/cases/assets/evidence.png" alt="VerdictAI Logo" width="100" />
</p>

<h1 align="center">⚖️ VerdictAI</h1>

<p align="center">
  <em>Multi-Agent Judicial Debate & Verdict System</em>
</p>

<p align="center">
  <a href="https://github.com/Morningstar202604/VerdictAI"><img src="https://img.shields.io/github/stars/Morningstar202604/VerdictAI?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/network/members"><img src="https://img.shields.io/github/forks/Morningstar202604/VerdictAI?style=social" alt="GitHub Forks" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/issues"><img src="https://img.shields.io/github/issues/Morningstar202604/VerdictAI" alt="GitHub Issues" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-FF6B35" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/WebSocket-Real--time-7C3AED" alt="WebSocket" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License" />
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">中文</a> · <a href="README.ja-JP.md">日本語</a>
</p>

---

> **7 AI experts walk into a courtroom.** They debate, challenge each other, cite evidence, run tools, catch contradictions — and converge on a verdict. All streamed live to your browser.

## ✨ What Makes VerdictAI Different?

| | Traditional AI Q&A | **VerdictAI** |
|---|---|---|
| Approach | Single model, single answer | **7 specialized agents** debate & challenge each other |
| Output | One-shot text | **Multi-round deliberation** with contradiction detection |
| Transparency | Black box | **Full event stream** — every token, tool call, agent status |
| Interactivity | Static | **Real-time WebSocket** — watch the debate unfold live |
| Verdict | "AI says so" | **Structured verdict** with evidence chain, open questions, recommendations |

## 🎯 Features

<details>
<summary><strong>🧠 7 Specialized AI Experts</strong></summary>

Each agent has a unique role, perspective, and system prompt:

| Expert | Role | Stance |
|--------|------|--------|
| 🔍 Crime Scene Analyst | Physical evidence, spatial relationships | Prosecution |
| 🔬 Forensic Specialist | Medical findings, DNA, cause of death | Neutral |
| 🧪 Evidence Analyst | Chain of custody, forensic integrity | Neutral |
| 🧠 Criminal Psychologist | Behavioral patterns, motive, profile | Neutral |
| ⚖️ Evidence Law Expert | Legal admissibility, procedure | Neutral |
| 👨‍⚖️ Prosecutor | Case for guilt, burden of proof | Prosecution |
| 🛡️ Defense Attorney | Reasonable doubt, alternatives | Defense |

</details>

<details>
<summary><strong>🔄 Multi-Round Debate Engine</strong></summary>

- Configurable 2–5 rounds of debate
- Experts see previous rounds' arguments and adapt
- AI critic catches contradictions each round
- Cross-round memory via summarized arguments
- Judge converges when consensus is reached

</details>

<details>
<summary><strong>🛠️ Tool-Augmented Reasoning</strong></summary>

Agents don't just talk — they **use tools**:

- `search_evidence` — Find evidence by keyword
- `check_timeline` — Verify event timing
- `list_contradictions` — Review flagged issues
- `search_statutes` — Look up legal references
- `annotate_evidence` — Mark evidence with notes

</details>

<details>
<summary><strong>📹 Real-Time Streaming</strong></summary>

Every action is streamed via WebSocket:

- Live token-by-token expert output
- Tool call results in real-time
- Agent status indicators
- Round progression tracking
- Contradiction highlights

</details>

<details>
<summary><strong>📄 PDF Case Intake</strong></summary>

Upload a case PDF and VerdictAI automatically:

1. Extracts text (PyMuPDF, 50-page / 60K-char limit)
2. Structures into dossier: suspects, victims, evidence, timeline
3. Generates 7 analysis charts (timeline, evidence, DNA, etc.)
4. Stores for debate

</details>

<details>
<summary><strong>⚖️ Dual Verdict Mode</strong></summary>

- **AI Judge** — Automated convergence and verdict delivery
- **Human Judge (HITL)** — Pause debate for human review, override AI conclusions

</details>

<details>
<summary><strong>📚 Case Library & Replay</strong></summary>

- Manage multiple cases
- Full debate transcripts persisted as JSON
- Replay past debates with complete event timeline
- Export verdict reports

</details>

## 🚀 Quick Start (30 seconds)

```bash
# Clone
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend

# Setup
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/Mac

pip install -r requirements.txt

# Run (mock mode — no API key needed!)
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

**Open http://localhost:8787** → Upload a PDF → Click "开始辩论" → Watch 7 AI experts argue live.

## 🔌 Connect a Real LLM

```env
# backend/.env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_ROUNDS=3
```

Restart the server. Works with any OpenAI-compatible API: DeepSeek, GLM, Qwen, Step, Ollama, and more.

## 🏗️ Architecture

```
Browser ──WebSocket──▶ FastAPI ──▶ LangGraph StateGraph
                                     │
                        ┌────────────┼────────────┐
                        ▼            ▼             ▼
                   7 Experts     Critic        Judge
                  (parallel)   (per round)   (verdict)
                        │            │             │
                        └────────────┘  loop N     ▼ done
```

**Key Design Decisions:**
- **LangGraph StateGraph** — Deterministic state machine, not ad-hoc loops
- **asyncio.gather** — 7 experts run in parallel per round
- **Tool fault tolerance** — Bad tool calls never crash the debate
- **Cross-round memory** — `round_summaries` list with `operator.add`

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full breakdown.

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System design, state machine, event types |
| [API Reference](docs/API.md) | REST endpoints & WebSocket protocol |
| [Deployment](docs/DEPLOYMENT.md) | Docker, systemd, Nginx, performance tuning |
| [Contributing](CONTRIBUTING.md) | Development setup & guidelines |

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development setup
- Code style guidelines
- PR process

## ⚠️ Disclaimer

This system is for **research and demonstration purposes only**. AI-generated verdicts do not constitute legal advice or judgments. All final legal responsibility rests with human judges and legal professionals.

## 📜 License

[MIT License](LICENSE) — use it for anything.

---

<p align="center">
  <strong>If you find VerdictAI useful, please consider giving it a ⭐</strong>
</p>

<p align="center">
  <sub>Built with LangGraph • FastAPI • WebSocket</sub>
</p>
