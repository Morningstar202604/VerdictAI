# VerdictAI · 发展规划与实施计划（v1.0）

> 定位：司法辅助多智能体审判推理引擎。七位专家举证质证 → 矛盾收敛 → 人类落槌。
> 本文档 = 现状盘点 + 行业对标 + 目标架构 + 分阶段任务 + 前后端 1:1 矩阵。
> 原则：**引轮子不造轮子**；**每层横向可扩展**；**横切能力贯穿所有层**。

---

## 1. 现状盘点（能力矩阵）

符号：✅ 已实现且验证 | 🟡 已有基础、需增强 | ⬜ 缺失

### 1.1 感知输入层（Intake）
| 能力 | 状态 | 说明 |
|---|---|---|
| PDF/DOCX/TXT 多格式解析 | ✅ | [documents.py](../backend/app/intake/documents.py)：PyMuPDF/pypdf 文本层 + pdfplumber 表格 + 60K 上限分段摘要 |
| 扫描件 OCR | ✅ | RapidOCR 本地 onnx（OCR_ENABLED 开关），缺失自动降级 |
| 图片视觉理解 | ✅ | [vision.py](../backend/app/intake/vision.py)：多模态描述 + OCR 兜底 |
| 意图识别（案由→预设） | 🟡 | [schemas.py](../backend/app/models/schemas.py) `cause_from_text`：确定性案由推导。**缺：实体槽位（当事人/时间/地点/金额）、置信度、无关输入门禁、多意图** |
| Pydantic 结构清洗 | ✅ | Intake/Verdict/Contradiction 三个模型全链路清洗 |

### 1.2 推理编排层（Reasoning）
| 能力 | 状态 | 说明 |
|---|---|---|
| 多智能体辩论（LangGraph） | ✅ | [builder.py](../backend/app/graph/builder.py)：experts→critic→judge→human_final，max_rounds 收敛 |
| 七角色专家并行/流式 | ✅ | PARALLEL_EXPERTS / STREAM_EXPERTS 开关 |
| 人类落槌（HITL） | ✅ | judge_mode=human 暂停等待，ws_detach_grace 断线保活 |
| 矛盾互查节点（critic） | ✅ | list_contradictions 跨角色矛盾清单 |
| **裁决前完整性自检** | ✅ | [nodes.py](../backend/app/agents/nodes.py) `_selfcheck_case`：裁决前确定性体检（未解释证据/未解决矛盾/缺法条引用 → 交人类复核） |
| **反思/自我批评节点** | ✅ | [nodes.py](../backend/app/agents/nodes.py) `reflect_node`：judge 前对各角色主张做可证伪性审查（Reflexion），产出反对理由 |
| **侦查计划（Planner）** | ✅ | [processor.py](../backend/app/intake/processor.py) `_build_investigation_plan`：复杂卷宗先产出"待证问题清单"再分发给专家 |

### 1.3 记忆层（Memory）
| 能力 | 状态 | 说明 |
|---|---|---|
| 会话工作记忆（DebateState） | ✅ | [models/state.py](../backend/app/models/state.py) 随图流转 |
| 情景记忆（辩论历史落盘） | ✅ | [debates.py](../backend/app/routers/debates.py) list/get + 前端 refreshDebates |
| 语义记忆（向量知识库） | ✅ | [retriever.py](../backend/app/legal/retriever.py) Chroma + bge-small-zh |
| **跨庭审案例沉淀** | ✅ | [runner.py](../backend/app/graph/runner.py)：庭审裁决回填为"类案/判例"，供下次检索（MemGPT 式长期记忆） |
| **相似案例推荐** | ✅ | [cases.py](../backend/app/routers/cases.py) `/api/cases/{id}/similar`：embedding 近邻 → 案例详情"相似案例" |
| 程序记忆（技能/工具注册表） | ✅ | [tools.py](../backend/app/agents/tools.py) TOOLS 注册 + tools_for_role 角色授权 |

### 1.4 工具/技能层（Tools）
| 能力 | 状态 | 说明 |
|---|---|---|
| 证据查阅/时间线核校/矛盾调取/法条检索/要求举证 | ✅ | 六件套 + TOOL_LABELS 前端标签 |
| 联网搜索（免 API） | ✅ | [search.py](../backend/app/agents/search.py)：SearXNG 主 + Bing HTML 兜底 + Tavily 预留，结果 TTL 缓存（30min）、URL 去重聚合、source_url 引用溯源 |
| Python 沙箱 | ✅ | docker/venv 双后端。容器模式默认断网 + 512MB/1 核/128 进程限额，subprocess 60s 超时；缺命令审批白名单 UI |

### 1.5 知识层（Knowledge）
| 能力 | 状态 | 说明 |
|---|---|---|
| 内置法条 + 自定义条目 | ✅ | [knowledge.py](../backend/app/legal/knowledge.py) GET/POST/DELETE 全具备 |
| 混合检索（关键词+语义） | ✅ | hybrid_search + 前端语义开关 |
| **Rerank 排序** | ✅ | [retriever.py](../backend/app/legal/retriever.py) ：bge-reranker 精排（可选依赖，缺失降级为混合检索现状） |
| **引用溯源（grounding）** | ✅ | [nodes.py](../backend/app/agents/nodes.py) `_extract_citations`：专家发言标注引用条目/来源 URL，前端渲染"来源"徽标（对标 Perplexity/NotebookLM） |

### 1.6 输出层（Outcome）
| 能力 | 状态 | 说明 |
|---|---|---|
| 审判长裁决 + 存疑点 + 处置建议 | ✅ | [schemas.py](../backend/app/models/schemas.py) Verdict 模型 |
| 追问 QA 面板 | ✅ | /api/qa + 前端 chips |
| 证据图表（matplotlib） | ✅ | [charts.py](../backend/app/charts.py) 沙箱出图 |
| **庭审核查报告导出** | ✅ | [reports.py](../backend/app/routers/reports.py)：Markdown/DOCX（裁决 + 矛盾 + 时间线 + 证据链 + 引用），缺 python-docx 降级纯 Markdown |
| **证据时间线可视化** | ✅ | [cases.py](../backend/app/routers/cases.py) `/api/cases/{id}/timeline`：跨证据抽取时间戳 → 横向时间线视图（事件可点击回证据） |
| **证据链强度/置信度标注** | ✅ | [nodes.py](../backend/app/agents/nodes.py) 自检产出 `strength` 评分；前端裁决渲染强度条与不确定性声明 |

### 1.7 横切面（Cross-cutting）
| 能力 | 状态 | 说明 |
|---|---|---|
| 鉴权/登录 | ✅ | [auth.py](../backend/app/auth.py) + test_login_security |
| 审计落盘（audit_prompts） | ✅ | 有落盘 + [admin.py](../backend/app/routers/admin.py) 用量/审计面板（`/api/admin/usage`） |
| 配置管理（Settings + 运行快照） | ✅ | [config.py](../backend/app/config.py) + test_config_snapshot |
| 降级容错 | ✅ | 所有可选能力缺失静默降级不阻断 |
| **可观测性（trace）** | ✅ | [runner.py](../backend/app/graph/runner.py)：每节点/轮次耗时落盘 + 用量统计 + SSE 事件流（`/api/events`） |
| **评估回归（eval set）** | ✅ | [test_evals.py](../backend/tests/test_evals.py)：golden case 断言（确定性意图、schema 清洗、输出结构、搜索缓存） |
| CI（矩阵 + 语法 + 冒烟） | ✅ | [ci.yml](../.github/workflows/ci.yml) 4 个 Python 版本 |

---

## 2. 竞品与行业对标（可借鉴功能清单）

| 来源 | 可借鉴 | 在本文的落点 |
|---|---|---|
| ChatGPT / Claude | 会话侧边栏、流式、可中断续跑 | 已有 ✅；历史庭审入口 **M2** 完善 |
| ChatGPT Canvas / 报告 | 结构化报告导出 | **M1.5 报告导出** |
| OpenAI Code Interpreter | 沙箱资源限额、会话回放 | 沙箱增强 **M3** |
| Perplexity / NotebookLM | grounding 引用溯源 + 来源认证 | **M2 引用溯源徽标** |
| DeepResearch | 多步迭代检索、资料收集计划 | **M2 侦查计划节点** |
| Reflexion / Self-Refine | 自我批评、可证伪性审查 | **M2 反思节点** |
| MetaGPT | 角色化 SOP、可插拔角色 | 已有 ✅（七角色） |
| OpenManus / Manus | Planner→Executor 显式规划 | **M2 侦查计划** |
| MemGPT / Letta / LangMem | 分层记忆：工作/情景/语义/程序 | 情景✅语义✅；**M2 案例沉淀** |
| LangGraph Studio / LangSmith | DAG 实时可视化 + trace 可观测 | **M3 实时流程图 + 会话 trace** |
| ChatLaw 等司法产品 | 法条引用、判决书生成 | 法条✅；**报告导出与其打通** |
| 大厂 RAG 实践 | rerank、分块、引文、缓存 | rerank **M3**；缓存 **M2** |

---

## 3. 目标架构：九层 + 横切（每层横向可扩展）

```
┌────────────────────────────────────────────────────────┐
│ 横切层 Cross-cut（贯穿所有层）                           │
│ 鉴权 · 审计落盘 · 用量观测 · 配置管理 · 缓存 · 降级容错  │
│ 安全校验 · 评估回归 · 统一日志/异常/度量 plumbing        │
├────────────────────────────────────────────────────────┤
│ L0 接入层 Ingress        REST / WS / (SSE) / (CLI 工具)  │  扩展: 多端接入、SSE、批量 CLI
│ L1 感知层 Intake         文档·视觉·OCR·意图路由·清洗      │  扩展: 语音/视频输入、多文档并行 intake
│ L2 推理层 Reasoning      planner→experts×N→critic→      │  扩展: 角色可插拔、反思/自检节点、
│                          judge→human_final             │        多图策略(速审/深审)
│ L3 记忆层 Memory         工作(会话state)·情景(辩论历史)  │  扩展: 每类记忆可换 provider、
│                          ·语义(向量)·程序(工具注册表)    │        案例沉淀/相似推荐
│ L4 工具层 Tools          证据·时间线·矛盾·法条·搜索·沙箱  │  扩展: 注册表白名单、角色授权、
│                                                       │        第三方工具插件
│ L5 知识层 Knowledge      builtin 法条·自定义·类案        │  扩展: 多来源混合、rerank、TTL 缓存
│ L6 输出层 Outcome        裁决·矛盾清单·报告导出·图表·     │  扩展: 多交付物格式、证据时间线、
│                          时间线·置信度                  │        强度条
│ L7 协作层 Human          落槌·质询·介入·续看·历史庭审     │  扩展: 多人协同审阅(M4)
└────────────────────────────────────────────────────────┘
```

**横向扩展约定（贯穿性约束）**
1. 每层通过**接口 + 注册表**暴露能力（仿 tools.py 的 TOOLS/TOOLS_BY_NAME 模式），新增实现只注册不侵入核心。
2. 可选能力一律带开关 + 缺失静默降级（对齐现有 EMBEDDING_MODEL=off / OCR_ENABLED 模式）。
3. 所有 Provider 类接口化：LLM（mock/openai/ollama 已有）、Embedding、Search、OCR、Storage。
4. 横切 plumbing 用 FastAPI 中间件 + 统一 `log=logging.getLogger("verdictai.*")` 命名贯穿。

---

## 4. 分阶段路线图

### M1（已完成，2026-09）
多格式文档/OCR/视觉解析、语义检索（Chroma+bge）、免 API 联网搜索、意图识别案由推导、案例库增强、Pydantic 清洗、React 版下线、CI 矩阵。

### M1.5（✅ 已完成，2026-09-10）
> 目标：把"只有基础"的功能补齐高级形态，全部零新框架。
| # | 任务 | 改动点 | 前端对应 | 验收 |
|---|---|---|---|---|
| 1.5.1 | **意图路由增强** | [schemas.py](../backend/app/models/schemas.py)：`intent_router` 返回 cause/preset/置信度 + 实体槽位（当事人/时间/地点/金额）；`gate_input` 过滤无关输入 | 新庭审输入 → 实时"识别预览"卡片 | 输入"你好"被判无关；"张三深夜入室盗窃"→ 盗窃案+槽位填充；pytest 覆盖 |
| 1.5.2 | **庭审核查报告导出** | 新 [routers/reports.py](../backend/app/routers/reports.py) `/api/debates/{id}/report`（Markdown + DOCX via python-docx），内容=裁决/矛盾/时间线/证据链/引用 | 裁决后工具条"导出报告"按钮 → 下载 | 导出含六章回卷内容；无 python-docx 降级纯 Markdown；测试 |
| 1.5.3 | **证据时间线** | 新 `/api/cases/{id}/timeline`（LLM 抽取证据时间戳，确定性兜底）；证据挂到时间点 | 辩论/案例详情切换"时间线"视图（横向 SVG） | 时间线按时间排序、事件可点击回证据；无 LLM 时有确定性兜底 |
| 1.5.4 | **相似案例推荐** | [routers/cases.py](../backend/app/routers/cases.py) `/api/cases/{id}/similar`（embedding 近邻；语义关时退关键词） | 案例详情"相似案例"卡片 | 返回 top3 + 相似度；语义关不报错 |
| 1.5.5 | **评估回归集** | [tests/test_evals.py](../backend/tests/test_evals.py) golden 断言：意图路由、schema 清洗、工具授权、时间线兜底 | — | CI 内全绿 |
| 1.5.6 | **搜索缓存 + 来源聚合** | [search.py](../backend/app/agents/search.py)：TTL 30min 结果缓存；多 provider 结果按 URL 去重合并 | 工具调用日志显示"缓存命中" | 同 query 二次调用不重复抓取；测试 |

### M2（✅ 已完成，2026-09-10 · 增强轮：推理与知识深化）
| # | 任务 | 说明 |
|---|---|---|
| 2.1 | 引用溯源 grounding | 专家发言携带引用条目/URL，前端渲染"来源"徽标（对标 Perplexity） |
| 2.2 | 反思节点 | judge 前可证伪性审查：各角色主张的反对理由必须被记录（Reflexion） |
| 2.3 | 完整性自检节点 | 裁决前确定性自检：未解释证据/未解决矛盾/缺法条引用 → 追加一轮或人工提示 |
| 2.4 | 侦查计划（Planner） | 复杂卷宗先产出"待证问题清单"再分发给七专家（DeepResearch 式） |
| 2.5 | 案例沉淀（长期记忆） | 庭审裁决回填 cases/ 为类案，进入知识检索 |
| 2.6 | 历史庭审入口完善 | 首页"历史庭审"列表 → 重开续看/导出 |
| 2.7 | 知识库管理前端 | tab-kb 增加"添加/删除自定义条目"表单（后端已具备） |

### M3（✅ 已完成，2026-09-10 · 专业轮）
| # | 任务 | 说明 |
|---|---|---|
| 3.1 | Rerank 精排 | bge-reranker 可选依赖，缺失降级为现状 |
| 3.2 | 证据链强度条/置信度 | 裁决附证据强度评分与不确定性声明 |
| 3.3 | 会话 trace + 用量面板 | 每步骤耗时/Token/成本；审计日志浏览 UI |
| 3.4 | 实时流程图 | 辩论中 LangGraph Studio 式节点实时点亮（复用 WS 事件） |
| 3.5 | 沙箱强化 | 超时/资源限额 UI、默认禁网、命令审批白名单 |

### M4（平台轮）
用户体系/RBAC、多人协同审阅、i18n/无障碍、语音录入(Whisper 本地)、联邦多来源知识库、SSE 接入层。

---

## 5. 前端后端 1:1 对应矩阵（目标态）

| 功能 | 后端 API | 前端位置 |
|---|---|---|
| 新庭审 + 意图预览 | POST /api/process & intent_router | 首页上传区/文本输入 + 识别预览卡片 |
| 多格式上传/OCR/视觉 | POST /api/process（file） | 首页拖拽区 |
| 案例库   列表/筛选/标签 | GET /api/cases, /tags | tab-library |
| 相似案例 | GET /api/cases/{id}/similar | 案例详情卡片 |
| 批量导入 | POST /api/cases/import_batch | tab-library 批量按钮 |
| 知识库 查询/新增/删除 | GET/POST /api/knowledge, DELETE | tab-kb（扩增表单） |
| 辩论 历史/详情/续看 | GET /api/debates | tab-library.历史庭审 + 详情 |
| 裁决/矛盾/追问 | WS + GET/POST /api/qa | 审理引擎页 |
| 联想时间线 | GET /api/cases/{id}/timeline | 案例详情"时间线"视图 |
| 报告导出 | GET /api/debates/{id}/report | 裁决工具条"导出报告" |
| 联网搜索 | POST /api/sandbox? web_search 工具 | 工具日志 + 设置 Provider |
| 专家配置/预设 | GET/PUT /api/agent-config, /api/presets | tab-agents / tab-board |
| 设置/引擎/环境 | GET/PUT /api/settings | tab-engine / tab-env |
| 用量/审计 | GET /api/admin/usage（M3） | tab-agent 或独立面板 |

---

## 6. 质量与发布

- 闸门：ruff 全绿 + pytest 全量 + 前端语法 + 端到端冒烟（CI 已覆盖）。
- 新增功能必须有对应 pytest（M1.5 #5 强制）。
- 可选依赖增强（python-docx/reranker 等）一律进 requirements-ai.txt，缺失降级。
- 变更后跑全量测试再提交；本阶段不推送，完成后统一 push + 开 PR。

## 7. 风险与回退
- 意图路由过度过滤 → gate 仅拦截明显无关输入，保留"继续分析"逃生按钮。
- 时间线抽取依赖 LLM → 确定性正则兜底 + 无结果显示空时间线不报错。
- 报告导出容量 → 60K 字符上限统一截断。
- 推理层新增节点不改变既有图拓扑（顺序插桩，不动 experts→critic→judge 主干），可整体开关。