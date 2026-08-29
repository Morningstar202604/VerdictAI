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

---

<p align="center">
  <strong>English</strong> · <a href="#中文">中文</a> · <a href="#日本語">日本語</a>
</p>

---

<a id="中文"></a>

## ⚖️ VerdictAI — 中文

> **7 位 AI 专家走进法庭。** 他们辩论、质疑、引用证据、调用工具、发现矛盾——最终收敛出裁决。全程实时流式传输到你的浏览器。

### 为什么选择 VerdictAI？

| 传统 AI 问答 | **VerdictAI** |
|---|---|
| 单模型、单次回答 | **7 位专家**多轮辩论、相互质疑 |
| 输出一次性文本 | **多轮审议** + 矛盾检测 |
| 黑盒 | **完整事件流** — 每 token、工具调用、Agent 状态 |
| 静态 | **实时 WebSocket** — 看辩论实时展开 |
| "AI 说的" | **结构化裁决** — 证据链、存疑点、建议 |

### 核心能力

- **7 位领域专家**：现场勘查 / 法医 / 物证 / 心理 / 证据法 / 检察官 / 辩护人
- **多轮辩论**：可配置 2–5 轮，专家互相审视论点
- **矛盾检测**：AI 纠错官每轮扫描矛盾
- **工具增强**：证据检索 / 时间线核对 / 法条查询 / 标注
- **PDF 案件提取**：拖入 PDF → 自动结构化
- **双模式审判**：AI 审判长 / 人类法官（HITL）
- **案例库 + 复盘**：多案件存储 + 历史辩论回放
- **零配置演示**：Mock 模式无需 API Key

### 快速开始

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

打开 `http://localhost:8787` 即可使用。

### 免责声明

本系统仅用于技术研究与演示。AI 生成的裁决不构成任何法律意见或判决。最终法律责任由人类法官承担。

---

<a id="日本語"></a>

## ⚖️ VerdictAI — 日本語

> **7人のAI専門家が法廷に入ります。** 彼らは議論し、疑義を呈し、証拠を引用し、ツールを使用し、矛盾を発見し、判決に到達します。すべてリアルタイムでブラウザにストリーミング。

### VerdictAI の特徴

| 従来の AI Q&A | **VerdictAI** |
|---|---|
| 単一モデル、単一回答 | **7人のエージェント**が議論・挑戦 |
| 1回限りのテキスト | **マルチラウンド審議** + 矛盾検出 |
| ブラックボックス | **完全なイベントストリーム** |
| 静的 | **リアルタイム WebSocket** |
| "AI が言った" | **構造化された判決** |

### 主な機能

- **7人の専門家**: 現場捜査 / 法医学 / 物証 / 心理学 / 証拠法 / 検察 / 弁護
- **マルチラウンド**: 2〜5ラウンドの設定が可能
- **矛盾検出**: AI批評官が各ラウンドの矛盾を検出
- **ツール拡張**: 証拠検索 / タイムライン確認 / 法令検索
- **PDF事件処理**: PDFをドロップ → 自動構造化
- **デュアル審判**: AI裁判長 / 人間裁判官（HITL）
- **ゼロコンフィグデモ**: MockモードでAPI Keyなしで動作

### クイックスタート

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

`http://localhost:8787` にアクセスしてご利用ください。

### 免責事項

本システムは技術研究・デモ用です。AIが生成した判決は法的助言や裁判の効力を持ちません。最終的な法的責任は人間の裁判官にあります。
