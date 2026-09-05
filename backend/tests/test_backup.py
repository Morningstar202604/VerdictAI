"""备份工具测试：打包内容正确、排除目录、保留策略修剪。"""

import os
import time
import zipfile
from pathlib import Path

from app.config import settings
from tools.backup import create_backup


def _make_data(tmp, monkeypatch):
    tmp = Path(tmp)
    monkeypatch.setattr(settings, "data_dir", str(tmp))
    (tmp / "cases").mkdir(parents=True, exist_ok=True)
    (tmp / "debates").mkdir(exist_ok=True)
    (tmp / "sandbox_out").mkdir(exist_ok=True)
    (tmp / "logs").mkdir(exist_ok=True)
    (tmp / "cases" / "case_x.json").write_text("{}", encoding="utf-8")
    (tmp / "debates" / "sess_x.json").write_text("{}", encoding="utf-8")
    (tmp / "knowledge_base.json").write_text("[]", encoding="utf-8")
    (tmp / "sandbox_out" / "chart.png").write_bytes(b"\x89PNG")
    (tmp / "logs" / "verdictai.log").write_text("log", encoding="utf-8")


def test_backup_includes_runtime_data_excludes_artifacts(tmp_path, monkeypatch):
    _make_data(str(tmp_path), monkeypatch)
    out = str(tmp_path / "backups")
    zip_path = create_backup(out_dir=out, keep=14)
    assert os.path.exists(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert os.path.join("cases", "case_x.json").replace("\\", "/") in {n.replace("\\", "/") for n in names}
    assert "debates/sess_x.json".replace("/", "\\") in names or "debates/sess_x.json" in names
    assert "knowledge_base.json" in names
    # 排除项
    assert not any("sandbox_out" in n for n in names)
    assert not any("logs" in n for n in names)


def test_backup_keep_prunes_old_archives(tmp_path, monkeypatch):
    import time

    _make_data(str(tmp_path), monkeypatch)
    out = str(tmp_path / "backups")
    for _ in range(3):
        create_backup(out_dir=out, keep=2)
        time.sleep(1.1)  # 时间戳精确到秒，确保文件名唯一
    leftovers = [f for f in os.listdir(out) if f.endswith(".zip")]
    assert len(leftovers) == 2
