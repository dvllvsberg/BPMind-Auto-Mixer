import pytest

from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import Track
from engine.mix_generator.mix_generator import MixGenerator, MixGeneratorConfig
from engine.mix_generator.wave_energy import WAVE_LOUD_DB, WAVE_QUIET_DB, wave_target_energy


def test_wave_target_energy_forms_sine_arc():
  total = 11
  values = [wave_target_energy(step, total) for step in range(total)]

  assert values[0] == pytest.approx(WAVE_QUIET_DB)
  assert values[-1] == pytest.approx(WAVE_QUIET_DB)
  assert max(values) == pytest.approx(WAVE_LOUD_DB)
  assert values[total // 2] == pytest.approx(WAVE_LOUD_DB)
  assert values[1] > values[0]
  assert values[-2] > values[-1]


def test_wave_target_energy_single_track():
  assert wave_target_energy(0, 1) == pytest.approx(WAVE_QUIET_DB)


def _track(track_id: int, title: str, *, loudness: float, bpm: float = 70.0) -> Track:
  return Track(
    id=track_id,
    path=f"/music/{title}.mp3",
    title=title,
    artist="Test",
    duration=180.0,
    file_size=1000,
    file_mtime=1.0,
    bpm=bpm,
    loudness_avg=loudness,
    loudness_peak=loudness + 3,
    analysis_level=AnalysisLevel.QUICK,
  )


def test_wave_mode_builds_louder_middle_than_edges():
  tracks = [
    _track(1, "Q1", loudness=-28.0),
    _track(2, "Q2", loudness=-26.0),
    _track(3, "Mid1", loudness=-18.0),
    _track(4, "Loud1", loudness=-10.0),
    _track(5, "Loud2", loudness=-11.0),
    _track(6, "Mid2", loudness=-19.0),
    _track(7, "Q3", loudness=-27.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=7, groove_weight=0.0))
  session = generator.generate(tracks, StartMode.WAVE, seed=1)

  by_id = {track.id: track for track in tracks}
  energies = [by_id[item.track_id].loudness_avg for item in session.tracks]

  assert energies[0] <= -24.0
  assert max(energies) >= -12.0
  assert energies[-1] <= -24.0
  assert max(energies) > energies[0]
  assert max(energies) > energies[-1]

  mid = len(energies) // 2
  assert energies[mid] >= energies[0]
  assert energies[mid] >= energies[-1]


def test_wave_mode_starts_near_quiet_target():
  tracks = [
    _track(1, "Quiet", loudness=-28.0),
    _track(2, "Loud", loudness=-10.0),
    _track(3, "Mid", loudness=-18.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=3, groove_weight=0.0))
  session = generator.generate(tracks, StartMode.WAVE, seed=1)

  assert session.tracks[0].track_id == 1
  assert session.start_mode == StartMode.WAVE
