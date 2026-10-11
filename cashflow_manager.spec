# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows 单文件 exe）。

用法：
    pyinstaller --noconfirm --clean cashflow_manager.spec

说明：
- 模板/静态资源/schema.sql 会被打进 exe，运行时通过 cashflow/resources.py
  的 resource_path() 定位（sys._MEIPASS）。
- 数据库文件不打包，运行后在 exe 同目录的 data/cashflow.db 创建。
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("cashflow/templates", "cashflow/templates"),
    ("cashflow/static", "cashflow/static"),
    ("cashflow/schema.sql", "cashflow"),
]

hiddenimports = collect_submodules("openpyxl") + [
    "jinja2.ext",
    "sqlite3",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CashflowManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 不使用 UPX：GitHub Actions 的 Windows runner 自带 upx.exe，
    # 压缩后的 python3xx.dll / onefile 在部分 Windows 上会出现启动即崩，
    # 而不压缩只多几 MB，稳定性优先。
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
