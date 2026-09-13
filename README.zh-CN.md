<p align="center">
  <img src="backend/app/static/assets/logo.svg" alt="VerdictAI Logo" width="110" />
</p>

<h1 align="center">⚖️ VerdictAI · 智能探案合议庭</h1>

<p align="center">
  <em>多智能体司法辩论与裁决系统</em>
</p>

<p align="center">
  <a href="https://github.com/Morningstar202604/VerdictAI/stargazers"><img src="https://img.shields.io/github/stars/Morningstar202604/VerdictAI?style=social" alt="GitHub Stars" /></a>
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
  <a href="README.md">English</a> · <strong>中文</strong> · <a href="README.ja-JP.md">日本語</a>
</p>

---

> **8 位 AI 庭审角色走进法庭。** 5 位鉴定人/辅助人 + 模拟控辩双方 + 人民陪审员，按「法庭调查 → 法庭辩论 → 评议」阶段剧本审查真实卷宗，多轮交叉质证，引用并核验法条，调用工具，互相纠错——最终由审判长按判决书结构起草参考裁决，落槌权始终归属人类法官。全程实时流式传输到你的浏览器。

**拿你自己的文档来。** 上传一份 PDF 侦查报告、起诉书或判决书——VerdictAI 会读懂它，抽取人员 / 证据 / 时间线 / 适用法条，为每位庭审角色定制分案材料，并展开一场完整的对抗式审议，最终产出判决书结构的参考裁决书（查明事实 / 逐证据认定 / 裁判说理 / 引用法条 / 裁决主文 / 量刑建议）与一份可供司法人员执行的后续流程清单。

## ✨ VerdictAI 有什么不同？

| | 传统 AI 问答 | **VerdictAI** |
|---|---|---|
| 模式 | 单模型、单次回答 | **8 个庭审角色智能体**多轮质证、相互质疑 |
| 产出 | 一次性文本 | **多轮审议** + 矛盾检测 |
| 透明度 | 黑盒 | **完整事件流**——每个 token、工具调用、Agent 状态 |
| 引用 | 幻觉编造 | **真实法条与类案要旨**——从知识库检索命中才引用，检索不到绝不编造；裁决引用的法条再做**内置法条库确定性核验**（未收录即标「疑似虚构」、法名未知即标「待人工核验」），量刑建议校验是否落在所引罪名的法定刑区间 |
| 文档 | 无法处理非结构化 | **AI 文档理解**——从纯 PDF 自动抽取人员/证据/时间线/法条 |
| 裁决 | "AI 说的" | **判决书结构裁决** + 逐证据三性认定 + 证据链 + 存疑点 + 可执行后续清单 |

## 📸 界面预览

| | |
|---|---|
| ![案件受理与品牌](docs/screenshots/landing.png) | ![实时庭审与人类介入](docs/screenshots/trial-debate.png) |
| *案件受理——PDF 上传、庭审阵容、AI 提取* | *实时庭审——8 位角色质证、人类介入、用量统计* |
| ![裁决与裁决后工作流](docs/screenshots/verdict-workflow.png) | ![深色模式](docs/screenshots/dark-mode.png) |
| *裁决书、质询、可执行后续清单* | *深色主题，完整笔录* |

## 🎯 功能

<details>
<summary><strong>🧑‍⚖️ 8 位 AI 庭审角色（按阶段剧本发言）</strong></summary>

5 位鉴定人/辅助人出庭接受质证，控辩双方对抗，人民陪审员以社会常理检验事实认定；发言按「法庭调查 → 法庭辩论 → 评议」阶段推进。

| 角色 | 职责 | 立场 |
|------|------|------|
| 🔍 勘查鉴定人 | 空间逻辑、出入动线、痕迹分布 | 出庭接受质证 |
| 🔬 法医鉴定人 | 死因、死亡时间窗、伤情 | 科学优先 |
| 🧪 物证鉴定人 | DNA、指纹、保管链、监控 | 物证为准 |
| 🧠 供述分析辅助人 | 供述与同步录音录像比对、非法取证线索 | 中立 |
| ⚖️ 证据法辅助人 | 证据资格、排除、证明标准 | 程序正义 |
| 👨‍⚖️ 公诉意见 Agent | 指控逻辑链、证明缺口 | 控方 |
| 🛡️ 辩护意见 Agent | 合理怀疑、替代解释 | 辩方 |
| 🧑‍💼 人民陪审员 | 社会常理检验：证据还原的事实是否可信、结论是否合常识 | 中立 |

</details>

<details>
<summary><strong>📄 真实文档理解</strong></summary>

上传叙述性 PDF 报告，AI 预处理自动完成：

1. 全文提取（PyMuPDF，50 页 / 6 万字符安全上限）
2. **从纯文本抽取结构**——人员（含角色）、证据、时间线、适用法条、资金/保险线索
3. 为每位专家生成分案材料，渲染案卷图表
4. 中文时间归一化（“凌晨1时30分至2时30分” → 标准死亡时间窗），供交叉验证

提取的结构在案卷面板带 **“✨ AI 自动提取”** 徽标，全部可编辑。

</details>

<details>
<summary><strong>🛠️ 工具增强推理</strong></summary>

专家不只说话——他们**调用工具**（结果直接渲染进笔录）：

- `read_evidence` — 按编号读取证据详情
- `timeline_check` — 与案件时间线核对事件时序
- `list_contradictions` — 查看已标记矛盾
- `search_case_law` — 三级法条检索：本案卷宗 → 自定义知识库 → 内置法条库
- `web_search` — 联网检索公开信息（Bing 国内源，可开关）
- `run_code` — 沙箱 Python（matplotlib 图表直接渲染进笔录）

</details>

<details>
<summary><strong>📚 知识库与类案</strong></summary>

- **内置法条库**：《刑事诉讼法》《刑法》《民法典》中编号稳定的真实条文 + 证据审查要旨（三性、保管链、电子数据）
- **类案要旨**：间接证据定案、监控剪辑影响、不可抗力抗辩等裁判规则
- **自定义条目**：在「设置 → 知识库」添加你自己的类案要旨或院内规范，三级检索命中才引用
- **绝不编造**：检索不到时专家会明说，而不是虚构法号
- **判决化裁决 + 引用核验**：审判长按判决书结构起草（查明事实 / 逐证据三性认定 / 裁判说理 / 引用法条 / 裁决主文 / 量刑建议）；裁决引用的法条再经**内置法条库确定性核验**（条文未收录 → 标「疑似虚构」、法名未知 → 标「待人工核验」，并交审判长回填修正一次），量刑建议校验是否落在所引罪名的**法定刑区间**

</details>

<details>
<summary><strong>🔄 多轮辩论引擎</strong></summary>

- 辩论轮数可配置，**记忆窗口**可配置
- 超出窗口的早期轮次**滚动压缩为摘要**，不直接丢弃
- AI 纠错官每轮扫描矛盾并推动下一轮深入
- 审判长在共识达成（或达到轮次上限）时收敛

</details>

<details>
<summary><strong>📹 实时流式与庭审体验</strong></summary>

- 逐 token 专家输出 + 发言呼吸灯
- 工具调用与沙箱图表直接渲染进笔录
- 轮次步进器、进度条、专家状态
- **中途介入**——随时插话，下一轮全体专家回应
- **裁决质询**——落槌后继续追问理由，带推荐追问

</details>

<details>
<summary><strong>⚖️ 双模式裁决与裁决后工作流</strong></summary>

- **AI 审判长**——自动收敛并落槌
- **人类法官（HITL）**——暂停庭审等待人工复核；超时自动采纳草案归档（可配置）
- **裁决之后**：质询追问、**后续流程清单**勾选跟踪、一键复制 / Markdown 导出 / 打印 PDF
- **结案卡片**：审理终结时笔录末尾呈现收束时刻——案名 / 轮数 / 推理次数，一键导出完整结案报告、打印 PDF 或开始新庭审
- 每场审理自动留档，带**用量统计**（推理次数、读写字符）与完整回放

</details>

<details>
<summary><strong>🧩 Agent 工程（设置 → Agent 工程）</strong></summary>

对标 Dify/Coze 的运行时工程参数：

- **记忆窗口**——注入每位专家上下文的前几轮摘要数
- **上下文上限**——单次 LLM 调用最大字符数（保护真实云端模型）
- **并行上限**——同轮专家并行数（限流友好）
- **调用超时**——引擎挂死不拖垮庭审
- **每专家模型覆盖**——书记员用便宜模型，审判长用最强模型
- **策略模板**——一键应用打包策略（“刑事·严格证据攻防”、“民事·责任划分”）
- **配置导入导出**——整套专家阵容 JSON 备份与迁移

</details>

<details>
<summary><strong>🧑‍⚖️ 审议质量——反思 · 自检 · 侦查计划</strong></summary>

- **反思节点（Reflexion 式）**——审判长收敛前，对每位专家的核心主张做可证伪性审查，反对理由必须被记录
- **完整性自检**——裁决前确定性体检：未解释证据 / 未解决矛盾 / 缺法条引用，交人类复核而非静默通过
- **侦查计划**——复杂卷宗先产出"待证问题清单"再分发给全体专家
- **案例沉淀**——每场结案裁决回填案件文件作为类案/判例，后续相似检索可复用
- **相似案例推荐**——案例详情页展示 embedding 近邻
- **证据链强度**——裁决附带强度评分与明确的不确定性声明

</details>

<details>
<summary><strong>🔎 检索 · 引用溯源与报告导出</strong></summary>

- **引用溯源 grounding**——专家发言携带其真实依据（法条/知识条目/来源 URL），前端渲染「来源」徽标（对标 Perplexity）；混合检索可叠加可选 BGE reranker 精排（`requirements-ai.txt` 安装，缺失自动跳过）
- **庭审核查报告**——一键导出 Markdown / DOCX，涵盖裁决、矛盾、时间线、证据链与引用
- **证据时间线视图**——跨证据抽取时间戳 → 交互式横向时间线
- **用量与审计面板**——`/api/admin/usage` 聚合每场会话的推理次数/字符量 + SSE 事件流实时监控
- **语音输入**——Chrome/Edge 支持 Web Speech API（zh-CN）时可直接口述案情

</details>

<details>
<summary><strong>🏛️ 部署就绪</strong></summary>

- 一键启动/停止（`tools/start_all.py`）——无窗口守护进程，崩溃自动重启
- 内网部署访问口令（`.env` 中 `ACCESS_PASSWORD`）——HMAC 签名会话令牌 + 登录限速防爆破
- 沙箱隔离——`run_code` 优先一次性 Docker 容器（断网、内存/CPU 上限），不可用自动降级本机子进程（`CODE_SANDBOX_BACKEND`）
- 数据备份——`tools/backup.py` 把案件/辩论/知识库打包为 zip 并自动修剪旧份
- 内置本地引擎完全离线可用，也可对接任意 OpenAI 兼容 API
- 明暗双主题，English / 中文 / 日本語 界面

</details>

## 🚀 快速开始（30 秒）

```bash
# 克隆
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend

# 环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/Mac

pip install -r requirements.txt

# 一键启动：后端 + 本地推理引擎（无窗口，崩溃自动重启）
python tools/start_all.py
# 停止：python tools/start_all.py stop
```

**生产部署（Docker）**：根目录 `docker compose up -d --build` → 内置 SPA（后端自带 UI）`:8787`，详见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

**打开 http://localhost:8787** → 拖入 PDF 卷宗（或粘贴案情/选示例）→ 看 AI 解析出结构化案卷 → 点击「开庭审理」→ 实时观看 8 位 AI 庭审角色质证。

## 🔌 接入真实大模型

```env
# backend/.env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_ROUNDS=3
```

重启服务即可。支持任意 OpenAI 兼容 API：DeepSeek、GLM、Qwen、Step、Ollama 等。没有 Key？内置**本地引擎**（`backend/ai_engine/`）可完全离线跑通全流程。

## 🏗️ 架构

```
浏览器 ──WebSocket──▶ FastAPI ──▶ LangGraph StateGraph
                                     │
                        ┌────────────┼────────────┐
                        ▼            ▼             ▼
                        8 位庭审角色   纠错官        审判长
                  （鉴定人/控辩/   （每轮）    （判决书结构
                     陪审员）         矛盾互查      起草参考裁决）
                        │            │             │
                        └────────────┘  循环 N     ▼ 完成
```

**关键设计决策：**
- **LangGraph StateGraph**——确定性状态机，而非临时拼凑的循环
- **asyncio.gather + 并发上限**——专家同轮并行，限流友好
- **工具容错**——错误的工具调用绝不会让辩论崩溃
- **分层记忆**——窗口内全文，窗口外滚动压缩
- **引用纪律**——法条/类案来自检索命中，绝不来自模型想象

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 📖 文档

| 文档 | 说明 |
|------|------|
| [架构](docs/ARCHITECTURE.md) | 系统设计、状态机、事件类型 |
| [API 参考](docs/API.md) | REST 端点与 WebSocket 协议 |
| [部署指南](docs/DEPLOYMENT.md) | Docker、systemd、Nginx、性能调优 |
| [贡献指南](CONTRIBUTING.md) | 开发环境搭建与规范 |

## 🤝 贡献

欢迎贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)：开发环境搭建、代码规范、PR 流程。

## ⚠️ 免责声明

本系统仅供**研究与演示**。AI 生成的结论是决策支持，不构成法律意见或判决。最终法律责任始终由人类法官与法律专业人员承担。

## 📜 许可证

[MIT License](LICENSE) — 自由使用。

---

<p align="center">
  <strong>如果 VerdictAI 对你有用，欢迎点一个 ⭐</strong>
</p>

<p align="center">
  <sub>Built with LangGraph • FastAPI • WebSocket</sub>
</p>
