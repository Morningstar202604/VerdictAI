<p align="center">
  <img src="backend/data/cases/assets/evidence.png" alt="VerdictAI Logo" width="100" />
</p>

<h1 align="center">⚖️ VerdictAI</h1>

<p align="center">
  <em>多智能体司法辩论与裁决系统</em>
</p>

<p align="center">
  <a href="https://github.com/Morningstar202604/VerdictAI"><img src="https://img.shields.io/github/stars/Morningstar202604/VerdictAI?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License" /></a>
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">中文</a> · <a href="README.ja-JP.md">日本語</a>
</p>

---

> **7 位 AI 专家走进法庭。** 他们辩论、质疑、引用证据、调用工具、发现矛盾——最终收敛出裁决。全程实时流式传输到你的浏览器。

## 为什么选择 VerdictAI？

| 传统 AI 问答 | **VerdictAI** |
|---|---|
| 单模型、单次回答 | **7 位专家**多轮辩论、相互质疑 |
| 输出一次性文本 | **多轮审议** + 矛盾检测 |
| 黑盒 | **完整事件流** — 每 token、工具调用、Agent 状态 |
| 静态 | **实时 WebSocket** — 看辩论实时展开 |
| "AI 说的" | **结构化裁决** — 证据链、存疑点、建议 |

## 核心能力

- **7 位领域专家**：现场勘查 / 法医 / 物证 / 心理 / 证据法 / 检察官 / 辩护人
- **多轮辩论**：可配置 2–5 轮，专家互相审视论点
- **矛盾检测**：AI 纠错官每轮扫描矛盾，推动下一轮深入
- **实时流式**：WebSocket 推送每 token、工具调用、Agent 状态
- **工具增强**：证据检索 / 时间线核对 / 矛盾清单 / 法条查询 / 标注
- **PDF 案件提取**：拖入 PDF → 自动结构化为案件摘要
- **双模式审判**：AI 审判长 / 人类法官（HITL）
- **案例库管理**：多案件存储 + 历史辩论复盘
- **零配置演示**：Mock 模式无需 API Key 即可跑通

## 快速开始（30 秒）

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

打开 `http://localhost:8787` → 上传 PDF → 点击「开始辩论」→ 实时观看 7 位 AI 专家辩论。

## 接入真实模型

```env
# backend/.env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_ROUNDS=3
```

重启即可。支持任何 OpenAI 兼容 API：DeepSeek、GLM、Qwen、Step、Ollama 等。

## 架构

```
浏览器 ──WebSocket──▶ FastAPI ──▶ LangGraph StateGraph
                                     │
                        ┌────────────┼────────────┐
                        ▼            ▼             ▼
                   7 位专家      纠错官        审判长
                  （并行）     （每轮）      （裁决）
                        │            │             │
                        └────────────┘  循环 N     ▼ 完成
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 文档

| 文档 | 说明 |
|------|------|
| [架构](docs/ARCHITECTURE.md) | 系统设计、状态机、事件类型 |
| [API 参考](docs/API.md) | REST 端点与 WebSocket 协议 |
| [部署指南](docs/DEPLOYMENT.md) | Docker、systemd、Nginx、性能调优 |
| [贡献指南](CONTRIBUTING.md) | 开发环境搭建与规范 |

## 贡献

欢迎贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 免责声明

本系统仅用于技术研究与演示。AI 生成的裁决不构成任何法律意见或判决。最终法律责任由人类法官承担。

## 许可证

[MIT License](LICENSE) — 自由使用。

---

<p align="center">
  <strong>如果觉得有用，请给个 ⭐</strong>
</p>

<p align="center">
  <sub>Built with LangGraph • FastAPI • WebSocket</sub>
</p>
