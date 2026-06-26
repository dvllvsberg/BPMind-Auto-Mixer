from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.paths import default_db_path, default_library_profile_path, default_mix_path, load_settings
from app.mix_settings import resolve_mix_config, uses_auto_mix_settings
from app.user_messages import format_user_error
from engine.analysis.deep_analysis_runner import DeepAnalysisRunner
from engine.analysis.quick_analysis_runner import QuickAnalysisRunner
from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import Track
from engine.library.library_profile import compute_library_profile, load_library_profile, save_library_profile
from engine.mix_generator.recipe_metadata import MixRecipeMetadata
from engine.mix_generator.mix_generator import MixGenerator, MixGeneratorError
from engine.export.session_renderer import SessionExportError, export_session
from engine.mix_generator.recipe_library import validate_recipe_tracks
from engine.mix_generator.session_store import load_mix_recipe, save_mix_session
from engine.scanning.library_scanner import LibraryScanner


def track_label(track: Track) -> str:
  artist = track.artist.strip()
  title = track.title.strip() or Path(track.path).stem
  if artist:
    return f"{artist} - {title}"
  return title


def _build_scan_summary(
  *,
  deep_requested: bool,
  force: bool,
  quick_total: int,
  quick_analyzed: int,
  deep_total: int,
  deep_analyzed: int,
  library_total: int,
  deep_skip_reason: str = "",
) -> str:
  parts: list[str] = [f"В библиотеке: {library_total} треков"]

  if quick_total > 0:
    parts.append(f"быстрый анализ: {quick_analyzed} из {quick_total}")
  elif not force:
    parts.append("быстрый анализ: новых треков нет")

  if not deep_requested:
    return ". ".join(parts) + "."

  if deep_total > 0:
    parts.append(f"глубокий анализ: {deep_analyzed} из {deep_total}")
  elif deep_skip_reason == "already_deep":
    parts.append("глубокий анализ: уже выполнен для всех треков (для повтора включите «Пересчитать»)")
  elif deep_skip_reason == "no_quick":
    parts.append("глубокий анализ: сначала нужен быстрый анализ треков")
  else:
    parts.append(
      "глубокий анализ: нечего обрабатывать — включите «Пересчитать анализ»"
    )

  return ". ".join(parts) + "."


class ScanAnalyzeWorker(QThread):
  progress = Signal(int, int, str)
  status = Signal(str)
  finished_ok = Signal(int, int, int, str)
  failed = Signal(str)

  def __init__(self, folder: Path, *, force: bool = False, deep: bool = False) -> None:
    super().__init__()
    self._folder = folder
    self._force = force
    self._deep = deep

  def run(self) -> None:
    try:
      with TrackRepository(default_db_path()) as repo:
        self.status.emit("Сканирование папки...")
        scanner = LibraryScanner(repo)
        scan = scanner.scan(self._folder)
        self.status.emit(
          f"Скан: {scan.total} файлов, +{scan.added} новых, ~{scan.unchanged} без изменений"
        )

        pending = repo.list_for_quick_analysis(include_analyzed=self._force)
        analyzed = 0
        failed = 0
        quick_total = len(pending)
        quick_analyzed = 0
        deep_total = 0
        deep_analyzed = 0
        deep_skip_reason = ""

        if pending:
          self.status.emit(f"Быстрый анализ: {len(pending)} треков...")

          def on_start(track: Track, index: int, total: int) -> None:
            self.progress.emit(index, total, track_label(track))

          runner = QuickAnalysisRunner(repo)
          quick_result = runner.run(force=self._force, on_track_start=on_start)
          quick_analyzed = quick_result.analyzed
          failed += quick_result.failed
          analyzed += quick_result.analyzed

        if self._deep:
          deep_pending = repo.list_for_deep_analysis(include_analyzed=self._force)
          deep_total = len(deep_pending)
          if deep_pending:
            self.status.emit(f"Глубокий анализ: {len(deep_pending)} треков...")

            def on_deep_start(track: Track, index: int, total: int) -> None:
              self.progress.emit(index, total, f"deep: {track_label(track)}")

            deep_runner = DeepAnalysisRunner(repo)
            deep_result = deep_runner.run(force=self._force, on_track_start=on_deep_start)
            deep_analyzed = deep_result.analyzed
            failed += deep_result.failed
            analyzed += deep_result.analyzed
          elif not self._force:
            mixable = repo.list_mixable()
            if mixable and all(track.analysis_level == AnalysisLevel.DEEP for track in mixable):
              deep_skip_reason = "already_deep"
            elif not mixable:
              deep_skip_reason = "no_quick"

        mixable = repo.list_mixable()
        if mixable:
          profile = compute_library_profile(mixable)
          save_library_profile(profile, default_library_profile_path())

        summary = _build_scan_summary(
          deep_requested=self._deep,
          force=self._force,
          quick_total=quick_total,
          quick_analyzed=quick_analyzed,
          deep_total=deep_total,
          deep_analyzed=deep_analyzed,
          library_total=scan.total,
          deep_skip_reason=deep_skip_reason,
        )
        self.finished_ok.emit(scan.total, analyzed, failed, summary)
    except Exception as exc:
      self.failed.emit(format_user_error(exc))


class MixBuildWorker(QThread):
  finished_ok = Signal(int, str)
  failed = Signal(str)

  def __init__(
    self,
    mode: StartMode,
    *,
    start_track_id: int | None = None,
    seed: int | None = None,
  ) -> None:
    super().__init__()
    self._mode = mode
    self._start_track_id = start_track_id
    self._seed = seed

  def run(self) -> None:
    try:
      settings = load_settings()
      profile = load_library_profile(default_library_profile_path())
      config = resolve_mix_config(settings, profile, mode=self._mode)

      with TrackRepository(default_db_path()) as repo:
        tracks = repo.list_mixable()
        if not tracks:
          self.failed.emit("Нет проанализированных треков. Сначала выполните сканирование и анализ.")
          return

        generator = MixGenerator(config)
        session = generator.generate(
          tracks,
          self._mode,
          start_track_id=self._start_track_id,
          seed=self._seed,
        )

      output = default_mix_path()
      metadata = MixRecipeMetadata(
        track_play_ratio=config.track_play_ratio,
        groove_weight=config.groove_weight,
        crossfade_duration_sec=config.crossfade_duration_sec,
        session_length_tracks=config.session_length,
        mix_settings_manual=uses_auto_mix_settings(settings),
        seed=self._seed,
      )
      save_mix_session(session, output, metadata=metadata)
      self.finished_ok.emit(len(session.tracks), session.start_mode.value)
    except MixGeneratorError as exc:
      self.failed.emit(str(exc))
    except Exception as exc:
      self.failed.emit(format_user_error(exc))


class ExportAudioWorker(QThread):
  progress = Signal(int, int, str)
  finished_ok = Signal(str, float)
  failed = Signal(str)

  def __init__(self, output_path: Path) -> None:
    super().__init__()
    self._output_path = output_path

  def run(self) -> None:
    try:
      mix_path = default_mix_path()
      if not mix_path.exists():
        self.failed.emit("Сначала постройте или откройте микс.")
        return

      session, _metadata = load_mix_recipe(mix_path)
      if not default_db_path().exists():
        self.failed.emit("База библиотеки не найдена.")
        return

      with TrackRepository(default_db_path()) as repo:
        tracks_by_id: dict[int, Track] = {}
        for item in session.tracks:
          track = repo.get_by_id(item.track_id)
          if track is not None and track.id is not None:
            tracks_by_id[track.id] = track

        problems = validate_recipe_tracks(session, repo)
        if problems:
          self.failed.emit("Экспорт невозможен:\n" + "\n".join(problems[:6]))
          return

        def on_progress(index: int, total: int, label: str) -> None:
          self.progress.emit(index, total, label)

        duration_sec = export_session(
          session,
          tracks_by_id,
          self._output_path,
          on_progress=on_progress,
        )

      self.finished_ok.emit(str(self._output_path), duration_sec)
    except SessionExportError as exc:
      self.failed.emit(str(exc))
    except Exception as exc:
      self.failed.emit(format_user_error(exc))


ExportWavWorker = ExportAudioWorker
