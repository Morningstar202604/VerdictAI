<p align="center">
  <img src="backend/app/static/assets/logo.svg" alt="VerdictAI Logo" width="120" />
</p>

<h1 align="center">⚖️ VerdictAI</h1>

<p align="center">
  <b>7 AI experts cross-examine a real case file, cite real statutes &amp; precedents,
  and hand you a structured verdict — no API key needed.</b>
</p>

<p align="center">
  <a href="https://github.com/x33834/VerdictAI"><img src="https://img.shields.io/github/stars/x33834/VerdictAI?style=for-the-badge&logo=github" alt="GitHub Stars" /></a>
  <a href="https://github.com/x33834/VerdictAI/releases/latest"><img src="https://img.shields.io/github/v/release/x33834/VerdictAI?style=for-the-badge&logo=semver" alt="Latest Release" /></a>
  <a href="https://github.com/x33834/VerdictAI/actions"><img src="https://img.shields.io/github/actions/workflow/status/x33834/VerdictAI/ci.yml?style=for-the-badge&logo=githubactions&logoColor=white&label=CI" alt="CI" /></a>
  <a href="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" /></a>
  <a href="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT" /></a>
</p>

<p align="center">
  <a href="https://x33834.github.io/VerdictAI/"><img src="https://img.shields.io/badge/🌐_Official_Website-Visit-brightgreen?style=flat-square" alt="Official Website" /></a>
  <a href="https://github.com/x33834/VerdictAI/releases/latest/download/VerdictAI.zip"><img src="https://img.shields.io/badge/⬇️_One--Click_Download-latest-blue?style=flat-square" alt="Download" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI"><img src="https://img.shields.io/badge/GitHub-Mirror-24292F?style=flat-square&logo=github" alt="GitHub Mirror" /></a>
  <a href="https://gitcode.com/badhope/VerdictAI"><img src="https://img.shields.io/badge/GitCode-Mirror-3A72BE?style=flat-square&logo=git" alt="GitCode" /></a>
  <a href="https://gitee.com/badhope/VerdictAI"><img src="https://img.shields.io/badge/Gitee-Mirror-C71D23?style=flat-square&logo=git" alt="Gitee-Mirror" /></a>
</p>

<p align="center"><b>Official sites</b> (GitHub Pages, both accounts, identical):
  <a href="https://x33834.github.io/VerdictAI/">x33834.github.io/VerdictAI</a> ·
  <a href="https://morningstar202604.github.io/VerdictAI/">morningstar202604.github.io/VerdictAI</a>
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">中文</a> · <a href="README.ja-JP.md">日本語</a>
</p>

---

## What makes it worth 5 minutes of your time

Most legal-AI demos give you a paragraph. VerdictAI runs a **real deliberation**:
you drop in a case PDF, and a built-in *local* reasoning engine reads it, extracts the
people / evidence / timeline / applicable statutes, and then **7 specialized experts
argue against each other over multiple rounds** — a critic flags contradictions,
the judge converges on a verdict, and you get an evidence chain plus an actionable
checklist. Every step streams live to your browser.

> No cloud API, no sign-up, no placeholder text: the bundled local engine (`ai_engine`,
> port 9100) produces real analysis of your actual case file out of the box.

| | Traditional AI chat | **VerdictAI** |
|---|---|---|
| Stance-taking | One model, one opinion | **7 experts debate &amp; challenge each other** |
| Output | One-shot text | **Multi-round deliberation + contradiction detection** |
| Trust | Black box | **Full live event stream** — every token, tool call, agent status |
| Citations | May hallucinate | **Real statutes &amp; precedents** retrieved (never invented) |
| Documents | Unstructured upload | **AI document understanding** — persons / evidence / timeline / statutes |
| Deliverable | "AI says so" | **Structured verdict** — evidence chain, open questions, next steps |

## Who it's for

- **Legal practitioners** — a second opinion on evidence chains and applicable statutes before you commit to an argument.
- **Law students &amp; researchers** — watch how cross-examination and burden-of-proof reasoning unfold, step by step.
- **Curious engineers** — a complete agent-engineering kit: parallel agents, tool use, memory tiers, HITL — all in ~30s from zero.

## See it in action

<a href="docs/screenshots/landing.png"><img src="docs/screenshots/landing.png" alt="Case intake" width="49%" /></a>
<a href="docs/screenshots/trial-debate.png"><img src="docs/screenshots/trial-debate.png" alt="Live trial" width="49%" /></a>

<a href="docs/screenshots/verdict-workflow.png"><img src="docs/screenshots/verdict-workflow.png" alt="Verdict workflow" width="49%" /></a>
<a href="docs/screenshots/dark-mode.png"><img src="docs/screenshots/dark-mode.png" alt="Dark mode" width="49%" /></a>

## Core capabilities

### 🧑‍⚖️ Seven experts, one case
Run in parallel every round, each with a distinct stance:

| Expert | Focus |
|---|---|
| 🔍 Crime Scene Analyst | Spatial logic, entry/exit, trace distribution |
| 🔬 Forensic Specialist | Cause of death, TOD window, injuries |
| 🧪 Evidence Analyst | DNA, fingerprints, custody chain, surveillance |
| 🧠 Behavioral Psych Expert | Statement credibility, motive, profiling |
| ⚖️ Evidence Law Expert | Admissibility, exclusion, proof standard |
| 👨‍⚖️ Prosecutor Agent | Charging chain, gaps, rebuttals |
| 🛡️ Defense Agent | Reasonable doubt, alternative explanations |

### 🔧 Experts that actually do things
They don't just talk — they call tools, and the results render into the transcript:
`read_evidence` · `timeline_check` · `list_contradictions` · `search_case_law` (three-tier)
· `web_search` (toggleable) · `run_code` (sandboxed Python; matplotlib charts land inline).

### 📄 Real document understanding
PyMuPDF reads up to 50 pages / 60K chars, extracts persons / evidence / timeline /
statutes from plain prose, and normalizes Chinese time expressions into a standard TOD
window for cross-validation. Every extraction carries an editable *"AI auto-extracted"* badge.

### ⚖️ Statute &amp; precedent knowledge base
Built-in stable provisions (Criminal Procedure Law, Criminal Law, Civil Code) plus
appeal-reasoning digests. Three-tier search **only cites what actually matches** — if
nothing matches, the agents say so instead of inventing citations.

### 💬 Multi-round debate engine
Configurable rounds &amp; memory window; old rounds compress into a rolling digest, a
critic feeds contradictions back every round, and the judge converges on consensus
(or the round cap).

### 🖥️ Live trial experience
Token-by-token streaming with speaking indicators, round stepper &amp; progress bar,
**human intervention** (interject mid-trial; every expert responds next round),
post-verdict Q&amp;A, dark mode, and EN / 中文 / 日本語 UI.

### ⚖️ Dual verdict mode
AI judge auto-converges, or a **human judge (HITL)** pauses to review. After verdict:
Q&amp;A, an executable **next-steps checklist** with progress, copy / Markdown export /
print-to-PDF, and a 🔨 closure card + full closure report.

### 🛠️ Agent engineering
Memory window, context limit, concurrency cap, call timeout, per-agent model overrides,
strategy presets, config import/export.

### 🚀 Deployment-ready
`python tools/start_all.py` — one-command start/stop, windowless daemons, auto-restart;
`ACCESS_PASSWORD` intranet gate with HMAC sessions; optional one-shot Docker sandbox for
`run_code`; `tools/backup.py` for data; runs fully offline.

## Get started — try it in ~30 seconds

```bash
# Option A · one-click release bundle
#   Windows / macOS / Linux — just download & unzip, then:
cd VerdictAI/backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tools/start_all.py                           # one command: backend + local engine

# Option B · from source
git clone https://gitcode.com/badhope/VerdictAI.git
# or mirror: git clone https://github.com/x33834/VerdictAI.git  # also: github.com/Morningstar202604/VerdictAI · gitcode.com/badhope/VerdictAI · gitee.com/badhope/VerdictAI
cd VerdictAI/backend && pip install -r requirements.txt && python tools/start_all.py

# Option C · Docker
docker compose up -d --build
```

Open **http://localhost:8787** → drop in a PDF (or paste a description) → watch it parse
into a structured dossier → click **Open Trial** → watch 7 experts argue live.

> 📦 Ready-made bundle: grab the latest **VerdictAI.zip** from the
> [Release page](https://github.com/x33834/VerdictAI/releases/latest) — no git needed.

## How a trial runs

```mermaid
flowchart LR
    A[Upload / paste case] --> B[AI extracts structured dossier<br/>persons·evidence·timeline·statutes]
    B --> C[7 experts debate in parallel<br/>multi-round · tools · contradiction checks]
    C --> D{Judge converged?}
    D -->|no| C
    D -->|yes| E[Structured verdict<br/>evidence chain·open questions·recommendations]
    E --> F[Actionable checklist<br/>+ closure report + Q&A]
```

## Model providers

Out of the box it connects to the **bundled local reasoning engine** (`backend/ai_engine`,
port 9100) — real deterministic analysis, no API key. Works with any OpenAI-compatible API
(DeepSeek, GLM, Qwen, Ollama …) via `LLM_BASE_URL` + `LLM_API_KEY` in `backend/.env`.

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://127.0.0.1:9100/v1
LLM_MODEL=verdict-local
MAX_ROUNDS=3
```

## Architecture

```mermaid
flowchart TB
    UI1["🌐 Built-in SPA frontend<br/>(index.html)"]
    API["⚖️ FastAPI · app/main.py<br/>REST · WebSocket · auth · rate-limit"]
    UI1 -->|WebSocket + REST| API

    subgraph GRAPH["LangGraph debate state machine (StateGraph)"]
        direction LR
        E1["7 experts<br/>parallel debate"] --> E2["Critic<br/>contradiction detection"]
        E2 --> E3["Presiding judge<br/>convergence"]
        E3 -->|not converged → next round| E1
        E3 --> E4["Verdict gavel<br/>HITL confirm"]
        E4 --> V["Verdict output<br/>structured verdict · review · Q&A"]
    end
    API --> GRAPH

    subgraph SUPPORT["Supporting capabilities"]
        direction LR
        S1["Case preprocessing<br/>PDF → structured extraction"]
        S2["Tools + code sandbox<br/>6 tools · isolated exec"]
        S3["Statute knowledge base<br/>3-tier search · precedents"]
        S4["Data / charts<br/>cases · debates · KB"]
    end
    API -. depends .-> SUPPORT

    subgraph MODELS["Model supply (switchable)"]
        direction LR
        M1["Local engine<br/>ai_engine :9100 (default)"]
        M2["OpenAI-compatible<br/>DeepSeek / GLM / Qwen …"]
        M3["mock offline placeholder"]
    end
    GRAPH -. calls .-> MODELS
```

**Why it's built this way** — LangGraph StateGraph (deterministic state machine, not ad-hoc
loops) · `asyncio.gather` + concurrency cap (parallel, rate-limit friendly) · tool fault
tolerance (one bad call never stalls a trial) · tiered memory (recent full, old compressed)
· citation discipline (statutes from retrieval, never imagination).

## Documentation

| Document | Description |
|----------|-------------|
| [Official website](https://x33834.github.io/VerdictAI/) | Features, screenshots &amp; download |
| [Architecture](docs/ARCHITECTURE.md) | System design, state machine, event types |
| [API Reference](docs/API.md) | REST endpoints &amp; WebSocket protocol |
| [Deployment](docs/DEPLOYMENT.md) | Docker, systemd, Nginx, performance tuning |
| [Contributing](CONTRIBUTING.md) | Dev setup &amp; guidelines |

## Honest words

This system is **research &amp; demonstration software**. AI-generated conclusions are
decision support, not legal advice — final responsibility always rests with human judges
and legal professionals. Where the knowledge base has no matching statute, the agents will
say exactly that rather than guess.

## License

[MIT License](LICENSE) — use it for anything.