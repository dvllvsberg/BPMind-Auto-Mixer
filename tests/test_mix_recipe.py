import json
from datetime import datetime
from pathlib import Path

import pytest

from engine.domain.enums import StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition
from engine.mix_generator.recipe_library import (
  recipe_file_stem,
  recipe_path_for_name,
  sanitize_recipe_name,
)
from engine.mix_generator.recipe_metadata import MixRecipeMetadata, RECIPE_SCHEMA_VERSION
from engine.mix_generator.session_store import load_mix_recipe, load_mix_session, save_mix_recipe, save_mix_session


def _sample_session() -> MixSession:
  return MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=120.0),
      MixSessionTrack(track_id=2, play_from_sec=3.0, play_until_sec=180.0),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=120.0,
        crossfade_duration_sec=8.0,
      )
    ],
    start_mode=StartMode.WAVE,
    created_at=datetime(2026, 6, 26, 12, 0, 0),
  )


def test_recipe_roundtrip_with_generator_metadata(tmp_path: Path):
  session = _sample_session()
  metadata = MixRecipeMetadata(
    name="Friday wave",
    track_play_ratio=0.82,
    groove_weight=0.28,
    crossfade_duration_sec=8.0,
    session_length_tracks=11,
    mix_settings_manual=False,
  )
  path = tmp_path / "friday_wave.json"
  save_mix_recipe(session, path, metadata=metadata)

  loaded_session, loaded_metadata = load_mix_recipe(path)

  assert loaded_session.start_mode == StartMode.WAVE
  assert len(loaded_session.tracks) == 2
  assert loaded_metadata.name == "Friday wave"
  assert loaded_metadata.track_play_ratio == 0.82
  assert loaded_metadata.groove_weight == 0.28
  assert loaded_metadata.session_length_tracks == 11

  raw = json.loads(path.read_text(encoding="utf-8"))
  assert raw["schema_version"] == RECIPE_SCHEMA_VERSION
  assert raw["generator"]["track_play_ratio"] == 0.82


def test_legacy_recipe_without_generator_still_loads(tmp_path: Path):
  legacy = {
    "start_mode": "random",
    "created_at": "2026-01-01T00:00:00",
    "tracks": [{"track_id": 1, "play_from_sec": 0.0, "play_until_sec": 90.0}],
    "transitions": [],
  }
  path = tmp_path / "legacy.json"
  path.write_text(json.dumps(legacy), encoding="utf-8")

  session = load_mix_session(path)
  _metadata = load_mix_recipe(path)[1]

  assert session.start_mode == StartMode.RANDOM
  assert len(session.tracks) == 1


def test_sanitize_recipe_name():
  assert sanitize_recipe_name("  Friday wave  ") == "Friday wave"
  assert recipe_file_stem("Friday wave") == "Friday_wave"
  assert "/" not in recipe_file_stem("mix/test")


def test_recipe_path_for_name(tmp_path: Path):
  path = recipe_path_for_name("Test set", mixes_dir=tmp_path)
  assert path == tmp_path / "Test_set.json"
