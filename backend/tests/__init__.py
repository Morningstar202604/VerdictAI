# 使 tests 成为可导入包：pytest 在 prepend 模式下会把包根（backend/）
# 加入 sys.path，从而 `from tests._p0_helpers import ...` 稳定可用，
# 与 CI / 本地 `python -m pytest` 行为一致。
