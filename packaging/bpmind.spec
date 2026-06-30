# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

repo_root = os.path.abspath(os.path.join(SPECPATH, ".."))
entry_script = os.path.join(repo_root, "run_app.py")
settings_example = os.path.join(repo_root, "settings", "default.json.example")

pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all("PySide6")
librosa_hiddenimports = collect_submodules("librosa")

icon_file = os.path.join(repo_root, "packaging", "app.ico")

a = Analysis(
  [entry_script],
  pathex=[repo_root],
  binaries=pyside6_binaries,
  datas=[
    (settings_example, "settings"),
    *pyside6_datas,
  ],
  hiddenimports=[
    "app",
    "engine",
    "sounddevice",
    "soundfile",
    "lameenc",
    "mutagen",
    "audioread",
    "scipy",
    "sklearn",
    "sklearn.utils._typedefs",
    *librosa_hiddenimports,
    *pyside6_hiddenimports,
  ],
  hookspath=[],
  hooksconfig={},
  runtime_hooks=[],
  excludes=["tkinter"],
  cipher=block_cipher,
  noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
  pyz,
  a.scripts,
  [],
  exclude_binaries=True,
  name="BPMind Auto Mixer",
  debug=False,
  bootloader_ignore_signals=False,
  strip=False,
  upx=False,
  console=False,
  disable_windowed_traceback=False,
  argv_emulation=False,
  target_arch=None,
  codesign_identity=None,
  entitlements_file=None,
  icon=icon_file if os.path.exists(icon_file) else None,
)

coll = COLLECT(
  exe,
  a.binaries,
  a.datas,
  strip=False,
  upx=False,
  upx_exclude=[],
  name="BPMind Auto Mixer",
)
