from pathlib import Path

from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel, TransitionCandidateKind
from engine.domain.models import EnergySegment, TransitionCandidate


def test_get_by_ids_bulk_hydrate(tmp_path: Path):
  db = tmp_path / "test.db"
  with TrackRepository(db) as repo:
    repo.upsert_file_record("/a.mp3", "A", "X", 100, 1.0)
    repo.upsert_file_record("/b.mp3", "B", "Y", 100, 1.0)
    tracks = repo.list_all()
    assert len(tracks) == 2
    track_a, track_b = tracks[0], tracks[1]

    repo.save_quick_analysis(track_a.id, 120.0, 128.0, -12.0, -3.0)
    repo.save_deep_analysis(
      track_b.id,
      [EnergySegment(start_sec=0.0, end_sec=10.0, energy=0.5)],
      [
        TransitionCandidate(
          id=None,
          track_id=track_b.id,
          position_sec=30.0,
          kind=TransitionCandidateKind.QUIET,
          confidence=0.9,
        ),
      ],
    )

    loaded = repo.get_by_ids([track_b.id, track_a.id, 9999])
    assert set(loaded) == {track_a.id, track_b.id}
    assert loaded[track_a.id].bpm == 128.0
    assert loaded[track_b.id].analysis_level == AnalysisLevel.DEEP
    assert len(loaded[track_b.id].energy_map) == 1
    assert len(loaded[track_b.id].transition_candidates) == 1
