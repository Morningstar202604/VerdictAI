# Changelog

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