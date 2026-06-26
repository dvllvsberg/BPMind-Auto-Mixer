# Changelog

## [Unreleased]

См. план v1.3 (доп. профили TEA) ниже.

## [1.3.0] — план

- Профили: echo out, bass swap, reverse reverb
- Составные цепочки переходов
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
