import tempfile
from pathlib import Path

import pytest

from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel, ScanAction
from engine.scanning.library_scanner import SUPPORTED_EXTENSIONS, LibraryScanner


def _create_dummy_audio(path: Path) -> None:
  path.write_bytes(b"ID3" + b"\x00" * 100)


@pytest.fixture
def temp_music_dir(tmp_path: Path) -> Path:
  music = tmp_path / "music"
  music.mkdir()
  _create_dummy_audio(music / "track_one.mp3")
  _create_dummy_audio(music / "track_two.flac")
  (music / "ignore.txt").write_text("skip")
  sub = music / "sub"
  sub.mkdir()
  _create_dummy_audio(sub / "nested.wav")
  return music


@pytest.fixture
def repo(tmp_path: Path) -> TrackRepository:
  db = tmp_path / "test.db"
  r = TrackRepository(db)
  yield r
  r.close()


def test_supported_extensions():
  assert ".mp3" in SUPPORTED_EXTENSIONS
  assert ".m4a" in SUPPORTED_EXTENSIONS


def test_scan_adds_files(temp_music_dir: Path, repo: TrackRepository):
  scanner = LibraryScanner(repo)
  result = scanner.scan(temp_music_dir)

  assert result.total == 3
  assert result.added == 3
  assert result.unchanged == 0

  tracks = repo.list_all()
  assert len(tracks) == 3
  for track in tracks:
    assert track.analysis_level == AnalysisLevel.NONE


def test_scan_skips_unchanged(temp_music_dir: Path, repo: TrackRepository):
  scanner = LibraryScanner(repo)
  scanner.scan(temp_music_dir)
  result = scanner.scan(temp_music_dir)

  assert result.added == 0
  assert result.updated == 0
  assert result.unchanged == 3


def test_scan_detects_file_change(temp_music_dir: Path, repo: TrackRepository):
  scanner = LibraryScanner(repo)
  scanner.scan(temp_music_dir)

  target = temp_music_dir / "track_one.mp3"
  target.write_bytes(b"ID3" + b"\x01" * 200)

  result = scanner.scan(temp_music_dir)
  assert result.updated == 1
  assert result.unchanged == 2

  track = repo.get_by_path(str(target.resolve()))
  assert track is not None
  assert track.analysis_level == AnalysisLevel.NONE


def test_upsert_actions(repo: TrackRepository):
  action = repo.upsert_file_record(
    path="/music/a.mp3",
    title="A",
    artist="Artist",
    file_size=1000,
    file_mtime=1.0,
  )
  assert action == ScanAction.ADDED

  action = repo.upsert_file_record(
    path="/music/a.mp3",
    title="A",
    artist="Artist",
    file_size=1000,
    file_mtime=1.0,
  )
  assert action == ScanAction.UNCHANGED

  action = repo.upsert_file_record(
    path="/music/a.mp3",
    title="A",
    artist="Artist",
    file_size=2000,
    file_mtime=2.0,
  )
  assert action == ScanAction.UPDATED
