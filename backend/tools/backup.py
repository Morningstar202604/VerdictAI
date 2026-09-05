# -*- coding: utf-8 -*-
"""VerdictAI 数据备份：把运行时数据（案件/辩论/知识库/配置）打包为 zip。

用法（在 backend 目录用 .venv 的 python 运行）：
    python tools/backup.py                     # 备份到 DATA_DIR/backups，保留最近 14 份
    python tools/backup.py --keep 7            # 只保留最近 7 份
    python tools/backup.py --out D:/backup/vai # 备份到另一块盘/网盘（推荐）

排除目录：sandbox_out/（沙箱产物）、logs/、backups/（自身）。
建议配合系统计划任务每日执行，并把 --out 指向数据盘之外的存储。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402

EXCLUDE_DIRS = {"sandbox_out", "logs", "backups"}
NAME_PREFIX = "verdictai-backup-"


def create_backup(out_dir: str | None = None, keep: int = 14) -> str:
    data_root = os.path.abspath(settings.data_dir)
    out_dir = os.path.abspath(out_dir or os.path.join(data_root, "backups"))
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(out_dir, f"{NAME_PREFIX}{stamp}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(data_root):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, os.path.relpath(p, data_root))
    _prune(out_dir, keep)
    return zip_path


def _prune(out_dir: str, keep: int) -> None:
    """只保留最近 keep 份备份（0 = 不限制）。"""
    if not keep or keep <= 0:
        return
    zips = sorted(
        fn for fn in os.listdir(out_dir)
        if fn.startswith(NAME_PREFIX) and fn.endswith(".zip")
    )
    for fn in zips[:-keep]:
        os.remove(os.path.join(out_dir, fn))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="VerdictAI 数据备份")
    ap.add_argument("--out", default=None, help="备份输出目录（默认 DATA_DIR/backups）")
    ap.add_argument("--keep", type=int, default=14, help="保留最近 N 份（0=不限，默认 14）")
    args = ap.parse_args(argv)
    path = create_backup(args.out, args.keep)
    print("备份完成:", path)


if __name__ == "__main__":
    main()
