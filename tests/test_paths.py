from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _reload_paths():
  if "app.paths" in sys.modules:
    return importlib.reload(sys.modules["app.paths"])
  import app.paths

  return app.paths


def test_dev_mode_uses_repo_root(monkeypatch, tmp_path):
  monkeypatch.delattr(sys, "frozen", raising=False)
  monkeypatch.setattr(sys, "executable", str(tmp_path / "fake.exe"), raising=False)
  paths = _reload_paths()
  assert paths.is_portable_mode()
  assert paths.application_root() == paths.executable_dir()


def test_frozen_without_flag_uses_appdata(monkeypatch, tmp_path):
  exe_dir = tmp_path / "Program Files" / "BPMind"
  exe_dir.mkdir(parents=True)
  exe = exe_dir / "BPMind Auto Mixer.exe"
  exe.touch()
  appdata = tmp_path / "LocalAppData"
  appdata.mkdir()

  monkeypatch.setattr(sys, "frozen", True, raising=False)
  monkeypatch.setattr(sys, "executable", str(exe), raising=False)
  monkeypatch.setenv("LOCALAPPDATA", str(appdata))
  monkeypatch.delenv("BPMIND_PORTABLE", raising=False)

  paths = _reload_paths()
  assert not paths.is_portable_mode()
  assert paths.application_root() == appdata / "BPMind Auto Mixer"


def test_portable_flag_uses_exe_dir(monkeypatch, tmp_path):
  exe_dir = tmp_path / "portable"
  exe_dir.mkdir()
  (exe_dir / "portable.flag").write_text("", encoding="utf-8")
  exe = exe_dir / "BPMind Auto Mixer.exe"
  exe.touch()
  appdata = tmp_path / "LocalAppData"
  appdata.mkdir()

  monkeypatch.setattr(sys, "frozen", True, raising=False)
  monkeypatch.setattr(sys, "executable", str(exe), raising=False)
  monkeypatch.setenv("LOCALAPPDATA", str(appdata))

  paths = _reload_paths()
  assert paths.is_portable_mode()
  assert paths.application_root() == exe_dir


def test_bpmind_portable_env_override(monkeypatch, tmp_path):
  exe_dir = tmp_path / "install"
  exe_dir.mkdir()
  exe = exe_dir / "BPMind Auto Mixer.exe"
  exe.touch()

  monkeypatch.setattr(sys, "frozen", True, raising=False)
  monkeypatch.setattr(sys, "executable", str(exe), raising=False)
  monkeypatch.setenv("BPMIND_PORTABLE", "1")

  paths = _reload_paths()
  assert paths.is_portable_mode()
  assert paths.application_root() == exe_dir
