# Changelog

## [Unreleased]

## [1.6.1] — 2026-06-28

Иконка приложения в окне, на панели задач и в portable exe.

### Добавлено

- Мастер-иконка `assets/icon-master.png` и сборка `packaging/app.ico` (скрипт `packaging/build_app_icon.py`)
- `application_icon()` — иконка в Qt и PyInstaller spec

## [1.6.0] — 2026-06-28

Редизайн GUI и portable-сборка для Windows (скачал → распаковал → запустил exe).

### Добавлено

- **Окно «Настройки»** — параметры микса, анализа, переходов и сохранённые сеты вынесены из главного окна
- **Portable Windows** — релиз `BPMind-Auto-Mixer-Windows-portable.zip` с `BPMind Auto Mixer.exe` (PyInstaller)
- GitHub Actions: сборка и публикация zip при push тега `v*`
- Автосоздание `cache/`, `mixes/`, `exports/`, `settings/default.json` при первом запуске exe

### GUI

- Главное окно: плейлист + плеер; компактная верхняя панель (путь · папка · скан · настройки)
- Иконки вместо текста на кнопках папки и настроек; символы на транспорте
- Progress bar фиксированной высоты — без скачков layout при экспорте/скане
- Подписи треков в плейлисте в формате «артист — трек · BPM»

### Исправлено

- Импорт `format_transition_arrow` при воспроизведении
- `SettingsWindow.refresh_saved_recipes_list` при старте

## [1.5.0] — 2026-06-28

TEA v1.5: единый junction API и multi-lane рендер; фикс reverse swell; режим «Нет» без переходов.

### Добавлено

- **Junction API** (`junction.py`) — единая точка рендера стыка для всех профилей; реестр `render_*_junction`
- **Multi-lane рендер** (`lanes.py`) — дорожки с огибающими, staged blend через `mix_lanes`; отладочный экспорт WAV по слоям (`write_junction_debug_wavs`)
- **Impact v2** — киношный стык: pitch-down outgoing, snap incoming, отдельная FX-дорожка (swoosh + punch)
- **Режим «Нет»** (`TransitionMode.NONE`) — сет без overlap и DSP; треки играют целиком (игнор play_ratio)
- **Opening envelope** (`segment_envelope.py`) — мягкий fade-in/fade-out на main body первого трека (live + export)
- CLI `--transition-mode none`
- 135 автотестов

### Исправлено

- **reverse_swell** — обрезка тихого префикса головы входящего; forward handoff с слышимой точки; без микропаузы (~30 ms) на стыке overlap → main
- **Таймлайн / экспорт** — `reserve_fade_sec` vs `overlap_output_sec` для reverse: длина рендера совпадает с планом сета
- **playback_rules** — `planned_incoming_main_skip` синхронизирован с junction-рендером (reverse, tape, none)
- Профили filter / echo / bass / vinyl переведены на junction + lanes API
- Legacy `cut` → `none` при загрузке рецептов и в `TransitionType.parse`

### GUI

- **Переходы: «Нет»** — в комбобоксе режима (не в списке профилей); комбобокс профиля скрыт вне режима «Фиксированный»
- Убран «резкий» (`cut`) из профилей отладки

### CLI

```powershell
python run_engine.py mix --transition-mode none
```

## [1.4.0] — 2026-06-28

TEA v1.4: авто-длительность переходов по профилю и BPM; staged overlap и reverb-out для профилей v1.3.

### Добавлено

- **Auto-duration (TEA v1.4)** — планировщик вычисляет `crossfade_duration_sec` для каждого перехода по профилю, BPM (такты), контексту пары и доступному хвосту трека; глобальный crossfade в настройках — верхняя граница

### Исправлено

- **filter_sweep, impact, reverse_swell, bass_swap** — staged overlap (как vinyl): эффект слышен на solo-части, входящий в конце
- **echo_out** → **reverb-out**: алгоритмический reverb на хвосте вместо hallway; подпись в GUI «reverb»
- Подкрутка длительностей и громкости filter / reverb / impact / reverse / bass_swap
- **reverb** — мягче comb, нарастающий LP-muffle к концу хвоста
- **reverse** — overlay на стыке, непрерывный forward B, отдельный эффект-слой; без паузы перед track B

### GUI

- Настройка «Кроссфейд» переименована в **«Макс. переход»** (верхняя граница auto-duration)

## [1.3.0] — 2026-06-25

TEA v1.3: шесть новых профилей переходов, continuous handoff в плеере, единый DSP для экспорта.

### Добавлено

- **TEA v1.3** — шесть новых профилей переходов в авто-режиме:
  - **эхо** (`echo_out`) — delay на хвосте при сложных парах
  - **бас-своп** (`bass_swap`) — обмен низами при близком BPM и хорошем groove
  - **удар** (`impact`) — акцент на более громком входящем треке
  - **реверс** (`reverse_swell`) — упрощённый reverse-reverb на голове входящего
  - **стоп ленты** (`tape_stop`) / **винил** (`vinyl_brake`) — редкие эффекты замедления
- Контекст TEA: `incoming_louder`, `has_energy_drop_outro`, `bpm_close`
- CLI `--transition` поддерживает все новые профили
- Continuous handoff в плеере: preload входящих, бесшовная смена треков без паузы в буфере
- Таймлайн и план воспроизведения (`timeline_plan`) — единые длительности для UI, плеера и экспорта
- 103 автотеста

### Исправлено

- **эхо** — hallway: хвост уходит в затухающие отражения, голову входящего встречает обратный swell; к концу overlap громкость нормализуется
- **Плеер** — seek на таймлайне не сбрасывает позицию на переход (handoff только при естественной смене трека)
- **Плеер (GUI)** — «Сейчас» и подсветка в списке синхронны с воспроизведением при continuous handoff
- **vinyl_brake** — одно торможение на всём overlap; откат ~90 ms и вход incoming ~0.5 s (фикс. время, не % длины перехода)
- **tape_stop** — solo tail: brake/spin, без overlap-mix; смягчение стыка на handoff
- Усилены DSP-эффекты (фильтр, tape/vinyl, impact); crossfade с задержкой входящего

### Добавлено (GUI)

- **Дополнительно → Переходы**: режим «Фиксированный (тест)» — один профиль на весь сет (tape, удар, реверс и т.д.)

### CLI

```powershell
python run_engine.py mix --transition-mode fixed --transition echo_out
python run_engine.py mix --transition-mode fixed --transition bass_swap
```

### Отложено

- Составные цепочки переходов — v1.4+
- См. [docs/transition-engine.md](docs/transition-engine.md)

## [2.0.0] — будущее

- Новый интерфейс (визуальный редизайн, VHS/Y2K и т.д.)
- Визуализация типов переходов на таймлайне

---

## [1.2.0] — 2026-06-27

Smart Transition Engine: умный выбор переходов между треками.

### Добавлено

- **TEA** — отдельный этап после Mix Builder (`engine/mix_pipeline.py`)
- Авто-режим: **плавный** и **фильтр (LP)** по контексту пары треков (BPM, groove, громкость)
- **Резкий** переход — только CLI (`--transition-mode fixed --transition cut`), не в авто
- Режимы **fixed** / **random** для отладки в CLI
- Подписи переходов в GUI: сводка сета и стрелки в списке треков
- Единый DSP для плеера и экспорта; legacy `crossfade` → `smooth_blend`
- 69 автотестов

### CLI

```powershell
python run_engine.py mix --mode wave
python run_engine.py mix --transition-mode fixed --transition filter_sweep
python run_engine.py mix --transition-mode random --seed 42
```

---

## [1.1.0] — 2026-06-27

Улучшения UX и работы с рецептами без смены движка переходов.

### Добавлено

- Глубокий анализ по умолчанию при сканировании; «Только быстрый анализ» и «Пересчитать» — в «Дополнительно»
- Список сохранённых сетов в GUI (двойной клик — открыть)
- Seed для random/wave в «Дополнительно» (CLI и продвинутые сценарии); сохраняется в рецептах
- Документация Smart Transition Engine: [docs/transition-engine.md](docs/transition-engine.md)

---

## [1.0.0] — 2026-06-26

Первый стабильный релиз локального авто-миксера.

### Возможности

- Сканирование папки, быстрый и глубокий анализ (BPM, громкость, energy map, точки перехода)
- Авто-профиль библиотеки (параметры микса под BPM-кластер и deep-анализ)
- Режимы микса: calm, peak, wave, random, from_track
- Подбор треков: BPM + энергия + groove (пары хвост → голова)
- GUI: воспроизведение, таймлайн, seek, сохранение/загрузка рецептов
- Экспорт в WAV и MP3
- CLI (`run_engine.py`) для анализа, микса, воспроизведения и экспорта
