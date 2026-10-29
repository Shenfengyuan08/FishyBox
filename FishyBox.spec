# -*- mode: python ; coding: utf-8 -*-
"""FishyBox 打包配置（文件夹模式 onedir）。

用法（在项目根目录执行）：
    pyinstaller FishyBox.spec

产物：dist/FishyBox/FishyBox.exe（双击运行；不再解压到临时目录，规避
"Could not create temporary directory!" 报错）
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static')]
binaries = []
hiddenimports = [
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'cryptography.hazmat.primitives.kdf.pbkdf2',
]

# 修复：cryptography 的 _rust.pyd 依赖 python3t.dll（Python 3.13+ 的
# abi3t 自由线程兼容 DLL，位于 Python 安装目录的 abi3t-compat 子目录）。
# PyInstaller 默认不会打包这个子目录，导致冻结后 "DLL load failed while importing _rust"。
_py_dir = os.path.dirname(sys.executable)
_abi3t = os.path.join(_py_dir, "abi3t-compat", "python3t.dll")
if os.path.exists(_abi3t):
    binaries.append((_abi3t, "."))
    binaries.append((_abi3t, os.path.join("cryptography", "hazmat", "bindings")))

# 把 pywebview / cryptography 的子模块与数据文件全部收集进来，
# 避免动态导入（尤其 cryptography 的 Rust 后端、pywebview 的 JS 桥）被漏掉
for _pkg in ('pywebview', 'cryptography'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL', 'IPython'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FishyBox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FishyBox',
)
