from __future__ import annotations

from engine.mix_generator.mix_generator import MixGeneratorError


def format_user_error(exc: BaseException) -> str:
  if isinstance(exc, MixGeneratorError):
    return str(exc)

  if isinstance(exc, FileNotFoundError):
    path = getattr(exc, "filename", None) or str(exc)
    return f"Файл не найден: {path}"

  if isinstance(exc, PermissionError):
    return "Нет доступа к файлу или папке. Проверьте права и что файл не занят другой программой."

  message = str(exc).strip()
  if message.startswith("name ") and "is not defined" in message:
    return "Внутренняя ошибка приложения. Перезапустите BPMind Auto Mixer."

  if not message or message.startswith("Traceback"):
    return "Произошла непредвиденная ошибка. Попробуйте ещё раз или включите «Пересчитать анализ»."

  return f"Ошибка: {message}"
