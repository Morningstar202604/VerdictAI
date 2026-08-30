# 本地审理引擎（ZCode AI 编写）

一个 OpenAI 兼容的聊天补全服务，可完全替代云端 LLM 驱动整套辩论系统。
不联网、零费用、秒级响应；以确定性案件分析逻辑生成专家陈述、矛盾清单与裁决。

## 能力

- 真·解析卷宗：人员 / 时间线 / 证据（可靠性、保管链）/ 法条 / 资金 / DNA / 通讯
- 交叉验证：死亡时间窗 × 监控缺失片段、身份不明 DNA、保管链瑕疵、异常资金时点
- 按角色生成有依据的 Markdown 陈述，跨轮引用自己与他人的上轮主张
- 工具调用：`read_evidence` / `timeline_check` / `search_case_law` / `run_code`
  （第 2 轮物证专家会生成 matplotlib 图表并渲染进笔录）
- 书记员 / 纠错官 / 审判长 / 分案法官节点输出严格 JSON
- 轮次按（案件, 角色）键控、由前序摘要数量推导——多场辩论并行互不干扰

## 启动

```bash
cd backend
python -m uvicorn ai_engine.server:app --host 127.0.0.1 --port 9100
```

## 接入系统

```bash
curl -X POST http://localhost:8787/api/settings -H "Content-Type: application/json" \
  -d '{"llm_provider":"openai_compatible","llm_base_url":"http://127.0.0.1:9100/v1","llm_model":"verdict-local","intake_model":"verdict-local-intake"}'
```

设置会持久化到 `backend/.env`。切回云端引擎改回原 `LLM_BASE_URL` 即可
（原配置备份在 `backend/.env.backup-orig`）；或用设置界面的「离线模拟」纯 mock 模式。

## 回归测试

```bash
cd backend
.venv/Scripts/python tools/debate_client.py --case case_001            # AI 落槌完整辩论
.venv/Scripts/python tools/debate_client.py --case case_001 --judge human            # 人类落槌
.venv/Scripts/python tools/debate_client.py --case case_001 --intervene "补充核对E-02"  # 中途介入
```
