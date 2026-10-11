"""启动入口测试。

这里锁住的是一个真实踩过的坑：英文 Windows（cp1252）控制台无法编码中文，
``print("数据库已初始化：...")`` 会抛 UnicodeEncodeError 让进程以非 0 退出——
在 GitHub Actions 的 Windows runner 上就表现为「打包成功但冒烟测试失败」。
"""

from __future__ import annotations

import os
import subprocess
import sys

from .conftest import ROOT


def _run(env_extra, tmp_path, *args):
    env = dict(os.environ)
    env.update(env_extra)
    env["CASHFLOW_DB"] = str(tmp_path / "db.sqlite")
    return subprocess.run(
        [sys.executable, "run.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_init_db_survives_ascii_only_console(tmp_path):
    """即使控制台只能编码 ASCII（比 Windows cp1252 更严格），也必须正常退出。"""
    result = _run({"PYTHONIOENCODING": "ascii"}, tmp_path, "--init-db")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "db.sqlite").exists()


def test_init_db_creates_seed_sellers(tmp_path):
    result = _run({"PYTHONIOENCODING": "utf-8"}, tmp_path, "--init-db")
    assert result.returncode == 0, result.stderr

    sys.path.insert(0, ROOT)
    from cashflow.db import connect

    connection = connect(str(tmp_path / "db.sqlite"))
    try:
        names = {row["seller_name"] for row in connection.execute("SELECT seller_name FROM seller")}
    finally:
        connection.close()
    assert {"TEST_USER", "Unknown"} <= names


def test_unexpected_error_returns_nonzero(tmp_path):
    """出错时要带 traceback 且返回非 0，方便 CI 定位。"""
    result = _run({"PYTHONIOENCODING": "utf-8"}, tmp_path, "--port", "not-a-number")
    assert result.returncode != 0
