# Changelog

## [0.3.0] - 2026-09-06
### Fixed
- /static/data 收敛为仅挂载 cases/assets：辩论全记录、agent_config、知识库、presets 不再有任何 URL 可直达（图表 URL 前缀保持兼容）。
- 登录 cookie 从口令哈希改为进程级随机密钥的 HMAC 签名令牌（7 天过期、重启失效、不可伪造）；口令与会话校验走 compare_digest；/login 失败 5 次锁定 15 分钟。
### Added
- 配置快照：辩论开场 debate_snapshot() 拍快照并全程传递，POST /api/settings 只影响新辩论；并发会话互不干扰。get_llm 缓存键补 max_tokens。
### Changed
- should_continue 的 max_rounds/judge_mode 读会话内值，不再回读全局。

## [0.2.2] - 2026-09-06
### Fixed
- 路径穿越：上传接口的案件 ID 与 WebSocket 的 session_id 参与服务端文件名拼接但未校验，补齐 validate_id 同等校验。
- 密钥泄露面：代码沙箱与 pip 子进程此前继承完整环境，LLM_API_KEY / ACCESS_PASSWORD 对专家生成的任意代码可见；按 LLM_*/ACCESS_* 前缀剥离，工具注入变量显式叠加。
- 落盘可靠性：新增 atomic_write_json（临时文件 + 原子替换）作为全部 JSON 存储的统一写入点，并钳制写入目标在 DATA_DIR 内；agent_config 读取侧容忍损坏 JSON 回退内置默认，半截文件只降级一项功能而非拖垮辩论。
### Changed
- 固定源的 HTTP 探测/检索改用 http.client 显式固定主机（web_search、debate_client、start_all），请求目标不再由字符串拼接间接构成。
- 血迹示意图表改 sin-hash 确定性生成，替代 random+seed。
- CI backend 矩阵补 Python 3.10，兑现 README「Python 3.10+」承诺。
### Added
- CONTRIBUTING 新增运行时纪律：运行时数据不入库、JSON 原子写入与损坏容忍、Secrets 前缀剥离约定、路径参数校验、README 版本下限必须被 CI 矩阵覆盖、依赖分运行时/开发两栏。
- 核心纯逻辑单测（收敛判定、文本分片、原子落盘、配置容错）与沙箱/输入校验回归测试（共 28 例）。

## [0.2.1] - 2026-09-05
### Fixed
- 案件标题去重双重失效：上传接口对同一文件句柄连续 json.load 导致同名计数永远为 0，"(副本N)" 后缀从不生成；generate 先落盘模板再统计导致自计数，每个新示例案件都误带 "(副本)" 后缀。
- `_extract_json` 被前后缀说明文本包裹时，数组切片被对象切片抢先返回，纠错官矛盾清单失真；改为取解析成功的最长切片。
### Added
- 后端 pytest 测试基线（CI 冒烟断言移植 + 纯函数单测 + 去重回归）与 ruff lint 基线（`backend/ruff.toml`，正确性类规则，范围内违规清零）；开发依赖独立为 `backend/requirements-dev.txt`；两者接入 CI，CONTRIBUTING 规定的检查套件自此可执行。
### Changed
- 运行时生成的案件图表资产（`backend/data/cases/assets/`）退出版本控制（每次运行重新绘制，跟踪副本只会漂移）。
- CONTRIBUTING 前端描述同步双前端现状（内置单文件 UI + React/Vite 应用）。

## [0.2.0] - 2026-09-04
### Changed
- 版本对齐 frontend package.json 0.2.0 基线；包含实时报告改进。