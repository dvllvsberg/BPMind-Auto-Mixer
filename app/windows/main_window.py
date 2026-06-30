from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
  QComboBox,
  QFileDialog,
  QGroupBox,
  QHBoxLayout,
  QInputDialog,
  QLabel,
  QLineEdit,
  QListWidget,
  QMessageBox,
  QProgressBar,
  QPushButton,
  QSlider,
  QSizePolicy,
  QVBoxLayout,
  QWidget,
)

from app.paths import (
  default_db_path,
  default_mix_path,
  exports_dir,
  load_settings,
  mixes_dir,
  save_settings,
)
from app.ui.icons import folder_icon, make_icon_button, settings_icon
from app.ui.timeline_widget import MixTimelineWidget, format_time
from app.workers import ExportAudioWorker, MixBuildWorker, ScanAnalyzeWorker, track_label
from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, PlannedTransition, Track
from engine.mix_generator.recipe_library import (
  recipe_file_stem,
  recipe_path_for_name,
  sanitize_recipe_name,
  validate_recipe_tracks,
)
from engine.mix_generator.recipe_metadata import MixRecipeMetadata
from engine.mix_generator.session_store import load_mix_recipe, load_mix_session, save_mix_recipe
from engine.playback.session_player import PlayerState, SessionPlayer
from engine.playback.timeline_plan import SessionTimeline, build_session_timeline
from app.windows.settings_window import SettingsWindow
from engine.transitions.display import (
  format_transition_arrow,
  summarize_session_transitions,
  transition_profile_label,
)
from engine.transitions.modes import TransitionMode

SESSION_END_PROMPT_SEC = 45.0
SESSION_END_PROMPT_MIN_SEC = 12.0


def _start_track_combo_label(track: Track, *, list_index: int) -> str:
  bpm = f"{track.bpm:.1f}" if track.bpm else "?"
  return f"{list_index}. {bpm} BPM  {track_label(track)}"


def _mix_list_label(
  track: Track,
  *,
  list_index: int,
  transition: PlannedTransition | None = None,
) -> str:
  title = track_label(track)
  bpm = f"{track.bpm:.0f}" if track.bpm else "?"
  suffix = ""
  if transition is not None and transition.type.normalized() is not TransitionType.NONE:
    suffix = f"  ·  {transition_profile_label(transition.type)}"
  return f"{list_index:02d}   {title}   ·   {bpm} BPM{suffix}"


class MainWindow(QWidget):
  def __init__(self) -> None:
    super().__init__()
    self.setWindowTitle("BPMind Auto Mixer")
    self.setMinimumWidth(520)
    self.setMinimumHeight(480)

    self._player: SessionPlayer | None = None
    self._tracks_by_id: dict[int, object] = {}
    self._mix_track_ids: list[int] = []
    self._scan_worker: ScanAnalyzeWorker | None = None
    self._mix_worker: MixBuildWorker | None = None
    self._export_worker: ExportAudioWorker | None = None
    self._ending_session = False
    self._session_end_prompt_shown = False
    self._session_play_to_end = False
    self._rebuild_after_session_end = False
    self._auto_play_after_mix = False
    self._session_timeline: SessionTimeline | None = None
    self._transitions_by_from: dict[int, PlannedTransition] = {}

    settings = load_settings()
    saved_folder = settings.get("library_path", "")

    self._folder_edit = QLineEdit(saved_folder)
    self._folder_edit.setPlaceholderText("Папка с музыкой")
    self._folder_edit.setReadOnly(True)
    self._folder_edit.setMaximumWidth(300)

    browse_btn = make_icon_button(
      folder_icon(self),
      tooltip="Выбрать папку",
    )
    browse_btn.clicked.connect(self._choose_folder)

    self._settings_btn = make_icon_button(
      settings_icon(self),
      tooltip="Настройки — параметры микса, анализа, переходов и сохранённые сеты",
    )
    self._settings_btn.clicked.connect(self._open_settings)

    self._settings = SettingsWindow(self)
    self._settings.recipe_open_requested.connect(self._load_recipe_from_path)

    self._scan_btn = QPushButton("Сканировать и анализировать")
    self._scan_btn.clicked.connect(self._start_scan_analyze)

    self._mode_combo = QComboBox()
    self._mode_combo.addItem("Спокойный (calm)", StartMode.CALM.value)
    self._mode_combo.addItem("Пик (peak)", StartMode.PEAK.value)
    self._mode_combo.addItem("Волна (wave)", StartMode.WAVE.value)
    self._mode_combo.addItem("Случайный (random)", StartMode.RANDOM.value)
    self._mode_combo.addItem("С трека (from_track)", StartMode.FROM_TRACK.value)
    self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

    self._start_track_combo = QComboBox()
    self._start_track_combo.setVisible(False)
    self._start_track_combo.setMinimumWidth(220)

    self._mix_btn = QPushButton("Построить микс")
    self._mix_btn.clicked.connect(self._start_build_mix)

    self._save_recipe_btn = QPushButton("Сохранить сет")
    self._save_recipe_btn.setToolTip("Сохранить текущий микс как рецепт (порядок, тайминги, параметры)")
    self._save_recipe_btn.clicked.connect(self._save_current_recipe)

    self._open_recipe_btn = QPushButton("Открыть сет")
    self._open_recipe_btn.setToolTip("Загрузить сохранённый рецепт и воспроизвести тот же микс")
    self._open_recipe_btn.clicked.connect(self._open_saved_recipe)

    self._export_audio_btn = QPushButton("Экспорт аудио")
    self._export_audio_btn.setToolTip("Сохранить микс в MP3 (320 kbps) или WAV (44.1 kHz, 16-bit)")
    self._export_audio_btn.clicked.connect(self._export_current_mix_audio)

    self._progress = QProgressBar()
    self._progress.setFixedHeight(18)
    self._progress.setTextVisible(False)
    self._progress.setValue(0)
    self._progress.setMaximum(1)

    self._status = QLabel("Готов к работе")
    self._status.setWordWrap(True)

    self._now_label = QLabel("Сейчас: —")
    self._now_label.setWordWrap(True)
    self._next_label = QLabel("Далее: —")
    self._next_label.setWordWrap(True)

    self._time_label = QLabel("0:00 / 0:00")
    self._timeline_widget = MixTimelineWidget()
    self._timeline_widget.seek_requested.connect(self._on_timeline_seek)

    self._volume_slider = QSlider(Qt.Orientation.Horizontal)
    self._volume_slider.setRange(0, 100)
    self._volume_slider.setValue(int(settings.get("playback_volume", 100)))
    self._volume_slider.setToolTip("Громкость воспроизведения")
    self._volume_slider.valueChanged.connect(self._on_volume_changed)

    self._mix_list = QListWidget()
    self._mix_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._mix_list.setMinimumHeight(180)
    self._mix_list.setToolTip("Клик — перейти к треку (или начать с него, если плеер остановлен)")
    self._mix_list.itemClicked.connect(self._on_mix_track_clicked)

    self._play_btn = QPushButton("▶")
    self._pause_btn = QPushButton("⏸")
    self._next_btn = QPushButton("⏭")
    self._prev_btn = QPushButton("⏮")
    self._stop_btn = QPushButton("⏹")

    self._play_btn.clicked.connect(self._play)
    self._pause_btn.clicked.connect(self._toggle_pause)
    self._next_btn.clicked.connect(self._next_track)
    self._prev_btn.clicked.connect(self._prev_track)
    self._stop_btn.clicked.connect(self._stop_playback)

    self._set_playback_enabled(False)

    folder_row = QHBoxLayout()
    folder_row.addWidget(self._folder_edit)
    folder_row.addWidget(browse_btn)
    folder_row.addWidget(self._scan_btn)
    folder_row.addWidget(self._settings_btn)
    folder_row.addStretch()

    mix_row = QHBoxLayout()
    mix_row.addWidget(self._mode_combo)
    mix_row.addWidget(self._start_track_combo, stretch=1)
    mix_row.addWidget(self._mix_btn)
    mix_row.addWidget(self._save_recipe_btn)
    mix_row.addWidget(self._open_recipe_btn)
    mix_row.addWidget(self._export_audio_btn)

    timeline_row = QHBoxLayout()
    timeline_row.addWidget(self._timeline_widget, stretch=1)
    timeline_row.addWidget(self._time_label)

    transport_row = QHBoxLayout()
    transport_row.addStretch()
    transport_row.addWidget(self._prev_btn)
    transport_row.addWidget(self._play_btn)
    transport_row.addWidget(self._pause_btn)
    transport_row.addWidget(self._next_btn)
    transport_row.addWidget(self._stop_btn)
    transport_row.addStretch()

    volume_row = QHBoxLayout()
    volume_row.addWidget(QLabel("Громкость"))
    volume_row.addWidget(self._volume_slider, stretch=1)

    playback_box = QGroupBox("Плеер")
    playback_layout = QVBoxLayout(playback_box)
    playback_layout.addWidget(self._now_label)
    playback_layout.addWidget(self._next_label)
    playback_layout.addLayout(timeline_row)
    playback_layout.addLayout(transport_row)
    playback_layout.addLayout(volume_row)

    playlist_box = QGroupBox("Плейлист")
    playlist_layout = QVBoxLayout(playlist_box)
    self._transitions_summary_label = QLabel("")
    self._transitions_summary_label.setWordWrap(True)
    self._transitions_summary_label.setStyleSheet("color: palette(mid);")
    playlist_layout.addWidget(self._transitions_summary_label)
    playlist_layout.addWidget(self._mix_list, stretch=1)

    layout = QVBoxLayout(self)
    layout.addLayout(folder_row)
    layout.addLayout(mix_row)
    layout.addWidget(self._progress)
    layout.addWidget(self._status)
    layout.addWidget(playlist_box, stretch=1)
    layout.addWidget(playback_box)

    self._ui_timer = QTimer(self)
    self._ui_timer.setInterval(400)
    self._ui_timer.timeout.connect(self._refresh_playback_ui)

    self._refresh_start_track_combo()
    self._settings.reload_library_profile_ui(StartMode.CALM)
    self._on_mode_changed()

    if default_mix_path().exists():
      self._load_mix_plan()
      self._status.setText("Найден сохранённый микс. Можно нажать Play.")

  def closeEvent(self, event) -> None:  # noqa: N802
    self._stop_playback()
    self._settings.close()
    super().closeEvent(event)

  def current_start_mode(self) -> StartMode:
    return StartMode(self._mode_combo.currentData())

  def _open_settings(self) -> None:
    self._settings.on_start_mode_changed(self.current_start_mode())
    self._settings.show()
    self._settings.raise_()
    self._settings.activateWindow()

  def _reset_progress(self) -> None:
    self._progress.setValue(0)
    self._progress.setMaximum(1)

  def _set_mode_combo(self, mode: StartMode) -> None:
    index = self._mode_combo.findData(mode.value)
    if index < 0:
      return
    self._mode_combo.blockSignals(True)
    self._mode_combo.setCurrentIndex(index)
    self._mode_combo.blockSignals(False)
    self._start_track_combo.setVisible(mode == StartMode.FROM_TRACK)

  def _apply_recipe_metadata_to_ui(self, metadata: MixRecipeMetadata, session: MixSession) -> None:
    self._set_mode_combo(session.start_mode)
    self._settings.apply_recipe_metadata(metadata, session)
    self._settings.on_start_mode_changed(session.start_mode)

  def _load_recipe_from_path(self, recipe_path: Path) -> bool:
    try:
      session, metadata = load_mix_recipe(recipe_path)
    except Exception as exc:
      QMessageBox.critical(self, "BPMind", f"Не удалось прочитать рецепт:\n{exc}")
      return False

    if not default_db_path().exists():
      QMessageBox.warning(self, "BPMind", "База библиотеки не найдена. Сначала просканируйте папку.")
      return False

    with TrackRepository(default_db_path()) as repo:
      problems = validate_recipe_tracks(session, repo)

    if problems:
      QMessageBox.warning(
        self,
        "BPMind",
        "Рецепт нельзя воспроизвести:\n\n" + "\n".join(f"• {item}" for item in problems[:8]),
      )
      return False

    self._stop_playback()
    save_mix_recipe(session, default_mix_path(), metadata=metadata)
    self._apply_recipe_metadata_to_ui(metadata, session)
    self._load_mix_plan()

    label = metadata.name or recipe_path.stem
    self._status.setText(f"Открыт сет «{label}»: {len(session.tracks)} треков, режим {session.start_mode.value}.")
    return True

  def _save_current_recipe(self) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    session, metadata = load_mix_recipe(mix_path)
    default_name = metadata.name or f"{session.start_mode.value}"
    name, ok = QInputDialog.getText(
      self,
      "Сохранить сет",
      "Название:",
      text=default_name,
    )
    if not ok:
      return

    clean_name = sanitize_recipe_name(name)
    if not clean_name:
      QMessageBox.warning(self, "BPMind", "Укажите название сета.")
      return

    target_dir = mixes_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = recipe_path_for_name(clean_name, mixes_dir=target_dir)
    if target_path.exists():
      reply = QMessageBox.question(
        self,
        "BPMind",
        f"Сет «{clean_name}» уже существует. Перезаписать?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
      )
      if reply != QMessageBox.StandardButton.Yes:
        return

    recipe_metadata = MixRecipeMetadata(
      name=clean_name,
      track_play_ratio=metadata.track_play_ratio,
      groove_weight=metadata.groove_weight,
      crossfade_duration_sec=metadata.crossfade_duration_sec,
      session_length_tracks=metadata.session_length_tracks,
      mix_settings_manual=metadata.mix_settings_manual,
      seed=metadata.seed,
    )
    save_mix_recipe(session, target_path, metadata=recipe_metadata)
    self._settings.refresh_saved_recipes_list()
    self._status.setText(f"Сет сохранён: {target_path.name}")

  def _open_saved_recipe(self) -> None:
    start_dir = str(mixes_dir())
    if not mixes_dir().exists():
      mixes_dir().mkdir(parents=True, exist_ok=True)

    path, _ = QFileDialog.getOpenFileName(
      self,
      "Открыть сет",
      start_dir,
      "Рецепт микса (*.json)",
    )
    if not path:
      return

    self._load_recipe_from_path(Path(path))

  def _suggested_export_path(self, *, extension: str = ".mp3") -> Path:
    exports_dir().mkdir(parents=True, exist_ok=True)
    if default_mix_path().exists():
      session, metadata = load_mix_recipe(default_mix_path())
      if metadata.name:
        return exports_dir() / f"{recipe_file_stem(metadata.name)}{extension}"
      return exports_dir() / f"bpmind_{session.start_mode.value}{extension}"
    return exports_dir() / f"bpmind_{datetime.now():%Y%m%d_%H%M}{extension}"

  def _export_current_mix_audio(self) -> None:
    if not default_mix_path().exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте или откройте микс.")
      return
    if self._export_worker and self._export_worker.isRunning():
      return

    suggested = str(self._suggested_export_path(extension=".mp3"))
    path, selected_filter = QFileDialog.getSaveFileName(
      self,
      "Экспорт аудио",
      suggested,
      "MP3 (*.mp3);;WAV (*.wav)",
      "MP3 (*.mp3)",
    )
    if not path:
      return
    lower = path.lower()
    if "wav" in selected_filter.lower():
      if not lower.endswith(".wav"):
        path += ".wav"
    elif not lower.endswith(".mp3") and not lower.endswith(".wav"):
      path += ".mp3"

    export_label = "MP3" if path.lower().endswith(".mp3") else "WAV"
    self._export_audio_btn.setEnabled(False)
    self._mix_btn.setEnabled(False)
    self._progress.setValue(0)
    self._progress.setMaximum(100)
    self._status.setText(f"Экспорт {export_label}...")

    self._export_worker = ExportAudioWorker(Path(path))
    self._export_worker.progress.connect(self._on_export_progress)
    self._export_worker.finished_ok.connect(self._on_export_finished)
    self._export_worker.failed.connect(self._on_export_failed)
    self._export_worker.finished.connect(lambda: self._export_audio_btn.setEnabled(True))
    self._export_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._export_worker.start()

  def _on_export_progress(self, index: int, total: int, label: str) -> None:
    self._progress.setMaximum(total)
    self._progress.setValue(index)
    short = label if len(label) <= 50 else label[:47] + "..."
    self._status.setText(f"Экспорт [{index}/{total}]: {short}")

  def _on_export_finished(self, path: str, duration_sec: float) -> None:
    self._reset_progress()
    minutes = duration_sec / 60.0
    ext = Path(path).suffix.lower().lstrip(".") or "audio"
    self._status.setText(f"{ext.upper()} готов: {Path(path).name} ({minutes:.1f} мин)")
    QMessageBox.information(
      self,
      "BPMind",
      f"Микс экспортирован ({ext.upper()}):\n{path}\n\nДлительность: {minutes:.1f} мин",
    )

  def _on_export_failed(self, message: str) -> None:
    self._reset_progress()
    self._status.setText(message)
    QMessageBox.critical(self, "BPMind", message)

  def _on_volume_changed(self, value: int) -> None:
    settings = load_settings()
    settings["playback_volume"] = value
    save_settings(settings)
    if self._player is not None:
      self._player.set_volume(value / 100.0)

  def _apply_player_volume(self) -> None:
    if self._player is not None:
      self._player.set_volume(self._volume_slider.value() / 100.0)

  def _update_time_label(self, position_sec: float) -> None:
    total = self._session_timeline.total_duration_sec if self._session_timeline else 0.0
    self._time_label.setText(f"{format_time(position_sec)} / {format_time(total)}")

  def _on_timeline_seek(self, session_sec: float) -> None:
    if self._player is None or self._player.state == PlayerState.STOPPED:
      return
    self._player.seek_to_session(session_sec)
    self._update_time_label(session_sec)

  def _on_mode_changed(self) -> None:
    mode_value = self._mode_combo.currentData()
    is_from_track = mode_value == StartMode.FROM_TRACK.value
    self._start_track_combo.setVisible(is_from_track)
    self._settings.on_start_mode_changed(self.current_start_mode())

  def _refresh_start_track_combo(self) -> None:
    self._start_track_combo.clear()
    if not default_db_path().exists():
      return

    with TrackRepository(default_db_path()) as repo:
      tracks = repo.list_mixable()

    for list_index, track in enumerate(tracks, start=1):
      if track.id is None:
        continue
      self._start_track_combo.addItem(
        _start_track_combo_label(track, list_index=list_index),
        track.id,
      )

  def _choose_folder(self) -> None:
    start = self._folder_edit.text() or str(Path.home())
    folder = QFileDialog.getExistingDirectory(self, "Выберите папку с музыкой", start)
    if not folder:
      return
    self._folder_edit.setText(folder)
    settings = load_settings()
    settings["library_path"] = folder
    save_settings(settings)
    self._status.setText(f"Папка: {folder}")

  def _start_scan_analyze(self) -> None:
    folder = self._folder_edit.text().strip()
    if not folder:
      QMessageBox.warning(self, "BPMind", "Сначала выберите папку с музыкой.")
      return
    if self._scan_worker and self._scan_worker.isRunning():
      return

    self._scan_btn.setEnabled(False)
    self._mix_btn.setEnabled(False)
    self._progress.setValue(0)
    self._progress.setMaximum(100)
    self._status.setText("Запуск сканирования и анализа...")

    force = self._settings.force_analyze
    deep = self._settings.deep_analyze

    if deep and default_db_path().exists():
      with TrackRepository(default_db_path()) as repo:
        mixable = repo.list_mixable()
        deep_pending = repo.list_for_deep_analysis(include_analyzed=force)
        if not deep_pending and mixable and all(
          track.analysis_level == AnalysisLevel.DEEP for track in mixable
        ):
          QMessageBox.information(
            self,
            "BPMind",
            "Глубокий анализ уже выполнен для всех треков.\n\n"
            "Включите «Пересчитать анализ» в Настройках, если хотите прогнать его заново.",
          )

    self._scan_worker = ScanAnalyzeWorker(Path(folder), force=force, deep=deep)
    self._scan_worker.progress.connect(self._on_analyze_progress)
    self._scan_worker.status.connect(self._status.setText)
    self._scan_worker.finished_ok.connect(self._on_scan_finished)
    self._scan_worker.failed.connect(self._on_worker_failed)
    self._scan_worker.finished.connect(lambda: self._scan_btn.setEnabled(True))
    self._scan_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._scan_worker.start()

  def _on_analyze_progress(self, index: int, total: int, label: str) -> None:
    self._progress.setMaximum(total)
    self._progress.setValue(index)
    short = label if len(label) <= 50 else label[:47] + "..."
    self._status.setText(f"Анализ [{index}/{total}]: {short}")

  def _on_scan_finished(self, total: int, analyzed: int, failed: int, summary: str) -> None:
    self._reset_progress()
    self._refresh_start_track_combo()
    self._settings.reload_library_profile_ui(self.current_start_mode())
    self._status.setText(summary)
    if failed > 0:
      QMessageBox.warning(
        self,
        "BPMind",
        f"{summary}\n\nОшибок при анализе: {failed}.",
      )
    elif analyzed == 0 and self._settings.deep_analyze:
      QMessageBox.information(self, "BPMind", summary)

  def _start_build_mix(self) -> None:
    if self._mix_worker and self._mix_worker.isRunning():
      return

    mode_value = self._mode_combo.currentData()
    mode = StartMode(mode_value)

    start_track_id: int | None = None
    if mode == StartMode.FROM_TRACK:
      if self._start_track_combo.count() == 0:
        QMessageBox.warning(self, "BPMind", "Нет треков для старта. Сначала просканируйте и проанализируйте библиотеку.")
        return
      start_track_id = self._start_track_combo.currentData()
      if start_track_id is None:
        QMessageBox.warning(self, "BPMind", "Выберите стартовый трек.")
        return

    self._mix_btn.setEnabled(False)
    self._status.setText("Построение микса...")

    transition_mode, fixed_transition = self._settings.current_transition_plan()
    mix_seed = self._settings.mix_seed(mode)
    if transition_mode is TransitionMode.RANDOM and mix_seed is None:
      mix_seed = 1

    self._mix_worker = MixBuildWorker(
      mode,
      start_track_id=start_track_id,
      seed=mix_seed,
      transition_mode=transition_mode,
      fixed_transition=fixed_transition,
    )
    self._mix_worker.finished_ok.connect(self._on_mix_built)
    self._mix_worker.failed.connect(self._on_worker_failed)
    self._mix_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._mix_worker.start()

  def _on_mix_built(self, count: int, mode_name: str) -> None:
    self._load_mix_plan()
    summary = self._transitions_summary_label.text()
    auto_play = self._auto_play_after_mix
    self._auto_play_after_mix = False
    if auto_play:
      self._status.setText(f"Новый микс: {count} треков, режим {mode_name}")
      self._play()
      return
    self._status.setText(f"Микс готов: {count} треков, режим {mode_name}. {summary}")
    QMessageBox.information(
      self,
      "BPMind",
      f"Mix Session собрана: {count} треков.\n\n{summary}",
    )

  def _on_worker_failed(self, message: str) -> None:
    self._reset_progress()
    self._status.setText(message)
    QMessageBox.critical(self, "BPMind", message)

  def _load_mix_plan(self) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      self._mix_track_ids = []
      self._transitions_by_from = {}
      self._session_timeline = None
      self._timeline_widget.set_timeline(None)
      self._update_time_label(0.0)
      self._transitions_summary_label.setText("")
      self._refresh_mix_list()
      return

    session = load_mix_session(mix_path)
    self._mix_track_ids = [item.track_id for item in session.tracks]
    self._transitions_by_from = {
      transition.from_track_id: transition for transition in session.transitions
    }
    self._transitions_summary_label.setText(summarize_session_transitions(session))

    if not default_db_path().exists():
      self._session_timeline = None
      self._timeline_widget.set_timeline(None)
      self._update_time_label(0.0)
      self._refresh_mix_list()
      return

    with TrackRepository(default_db_path()) as repo:
      self._tracks_by_id = {}
      for track_id in self._mix_track_ids:
        track = repo.get_by_id(track_id)
        if track is not None:
          self._tracks_by_id[track_id] = track

    self._session_timeline = build_session_timeline(session, self._tracks_by_id)
    self._timeline_widget.set_timeline(self._session_timeline)
    self._update_time_label(0.0)
    self._refresh_mix_list()

  def _refresh_mix_list(self) -> None:
    self._mix_list.clear()
    for list_index, track_id in enumerate(self._mix_track_ids, start=1):
      track = self._tracks_by_id.get(track_id)
      if track is None:
        self._mix_list.addItem(f"{list_index}. [трек {track_id} недоступен]")
        continue
      transition = self._transitions_by_from.get(track_id)
      self._mix_list.addItem(
        _mix_list_label(track, list_index=list_index, transition=transition),
      )

  def _highlight_mix_list_row(self, row: int | None) -> None:
    self._mix_list.blockSignals(True)
    if row is None or row < 0 or row >= self._mix_list.count():
      self._mix_list.clearSelection()
    else:
      self._mix_list.setCurrentRow(row)
    self._mix_list.blockSignals(False)

  def _on_mix_track_clicked(self, item) -> None:
    row = self._mix_list.row(item)
    if row < 0:
      return

    if self._player is not None and self._player.state != PlayerState.STOPPED:
      self._player.jump_to_track(row)
      self._refresh_playback_ui()
      return

    self._play_from_index(row)

  def _play_from_index(self, index: int) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    self._load_mix_plan()
    session = load_mix_session(mix_path)
    if not self._tracks_by_id:
      QMessageBox.warning(self, "BPMind", "В миксе нет доступных треков.")
      return

    self._stop_playback()
    self._reset_session_end_state()
    self._player = SessionPlayer(session, self._tracks_by_id)
    self._apply_player_volume()
    self._player.play(start_index=index)
    self._set_playback_enabled(True)
    self._ui_timer.start()
    self._status.setText("Воспроизведение")
    self._refresh_playback_ui()

  def _play(self) -> None:
    if self._player is not None:
      state = self._player.state
      if state == PlayerState.PLAYING:
        return
      if state == PlayerState.PAUSED:
        self._player.play()
        self._set_playback_enabled(True)
        self._ui_timer.start()
        self._status.setText("Воспроизведение")
        self._refresh_playback_ui()
        return

    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    self._load_mix_plan()
    session = load_mix_session(mix_path)
    if not self._tracks_by_id:
      QMessageBox.warning(self, "BPMind", "В миксе нет доступных треков.")
      return

    self._stop_playback()
    self._reset_session_end_state()
    self._player = SessionPlayer(session, self._tracks_by_id)
    self._apply_player_volume()
    self._player.play(start_index=0)
    self._set_playback_enabled(True)
    self._ui_timer.start()
    self._status.setText("Воспроизведение")
    self._refresh_playback_ui()

  def _toggle_pause(self) -> None:
    if self._player is None:
      return
    state = self._player.toggle_pause()
    self._status.setText("Пауза" if state == PlayerState.PAUSED else "Воспроизведение")

  def _next_track(self) -> None:
    if self._player is None:
      return
    if not self._player.next_track():
      self._on_session_playback_finished()

  def _prev_track(self) -> None:
    if self._player is None:
      return
    self._player.previous_track()

  def _reset_session_end_state(self) -> None:
    self._session_end_prompt_shown = False
    self._session_play_to_end = False
    self._rebuild_after_session_end = False

  def _session_end_prompt_threshold_sec(self, duration_sec: float) -> float:
    if duration_sec <= 0:
      return SESSION_END_PROMPT_SEC
    return min(SESSION_END_PROMPT_SEC, max(SESSION_END_PROMPT_MIN_SEC, duration_sec * 0.15))

  def _maybe_prompt_session_ending(self, status) -> None:
    if self._player is None or self._session_end_prompt_shown or self._session_play_to_end:
      return
    if self._player.state != PlayerState.PLAYING:
      return

    duration = status.session_duration_sec
    remaining = duration - status.session_position_sec
    if remaining <= 0.5 or duration <= 0:
      return

    threshold = self._session_end_prompt_threshold_sec(duration)
    if remaining > threshold:
      return

    self._session_end_prompt_shown = True

    box = QMessageBox(self)
    box.setWindowTitle("BPMind")
    box.setText("Микс подходит к концу.\nПродолжим вечеринку?")
    box.setIcon(QMessageBox.Icon.Question)
    rebuild_btn = box.addButton("Пересобрать", QMessageBox.ButtonRole.ActionRole)
    continue_btn = box.addButton("Продолжить", QMessageBox.ButtonRole.AcceptRole)
    finish_btn = box.addButton("Завершить", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(continue_btn)
    box.exec()

    clicked = box.clickedButton()
    if clicked is rebuild_btn:
      self._rebuild_after_session_end = True
      self._session_play_to_end = True
      self._player.set_loop_session(False)
      self._status.setText("Воспроизведение · до конца, затем новый микс")
      return

    if clicked is continue_btn:
      self._session_play_to_end = False
      self._player.set_loop_session(True)
      self._session_end_prompt_shown = False
      self._status.setText("Воспроизведение · сет по кругу")
      return

    # «Завершить» или закрытие окна — доиграть сет и остановиться.
    self._session_play_to_end = True
    self._player.set_loop_session(False)
    self._status.setText("Воспроизведение · до конца сета")

  def _on_session_playback_finished(self) -> None:
    if self._ending_session:
      return
    self._ending_session = True
    rebuild_after = self._rebuild_after_session_end
    self._ui_timer.stop()
    if self._player is not None:
      self._player.stop()
      self._player = None
    self._set_playback_enabled(False)
    self._now_label.setText("Сейчас: —")
    self._next_label.setText("Далее: —")
    self._highlight_mix_list_row(None)
    self._reset_session_end_state()
    self._ending_session = False
    if rebuild_after:
      self._status.setText("Пересборка микса...")
      self._auto_play_after_mix = True
      self._start_build_mix()
      return
    self._status.setText("Конец сета")

  def _stop_playback(self) -> None:
    self._ui_timer.stop()
    if self._player is not None:
      self._player.stop()
      self._player = None
    self._reset_session_end_state()
    self._set_playback_enabled(False)
    self._now_label.setText("Сейчас: —")
    self._next_label.setText("Далее: —")
    self._highlight_mix_list_row(None)
    self._timeline_widget.set_position(0.0)
    self._update_time_label(0.0)

  def _set_playback_enabled(self, active: bool) -> None:
    self._pause_btn.setEnabled(active)
    self._next_btn.setEnabled(active)
    self._prev_btn.setEnabled(active)
    self._stop_btn.setEnabled(active)

  def _refresh_playback_ui(self) -> None:
    if self._player is None:
      return

    now = self._player.now_playing()
    if now is None:
      if self._player.state == PlayerState.STOPPED:
        self._on_session_playback_finished()
      return

    status = self._player.playback_status()
    if self._player.loop_session and status.session_position_sec < SESSION_END_PROMPT_MIN_SEC:
      self._session_end_prompt_shown = False

    self._maybe_prompt_session_ending(status)

    bpm = f"{now.track.bpm:.1f}" if now.track.bpm else "?"
    self._now_label.setText(f"Сейчас [{now.index}/{now.total}]  {bpm} BPM  {track_label(now.track)}")
    self._highlight_mix_list_row(self._player.current_index)

    self._update_time_label(status.session_position_sec)
    if not self._timeline_widget.is_dragging():
      self._timeline_widget.set_position(status.session_position_sec)

    next_text = "Далее: —"
    if self._player.current_index + 1 < len(self._mix_track_ids):
      next_id = self._mix_track_ids[self._player.current_index + 1]
      next_track = self._tracks_by_id.get(next_id)
      if next_track is not None:
        nbpm = f"{next_track.bpm:.1f}" if next_track.bpm else "?"
        next_text = f"Далее: {nbpm} BPM  {track_label(next_track)}"
        current_id = self._mix_track_ids[self._player.current_index]
        transition = self._transitions_by_from.get(current_id)
        if transition is not None:
          hint = format_transition_arrow(transition).strip()
          if hint.startswith("→"):
            next_text += f"  {hint}"
    self._next_label.setText(next_text)
