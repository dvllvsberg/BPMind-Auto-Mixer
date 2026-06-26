from app.user_messages import format_user_error


def test_format_user_error_hides_python_internals():
  try:
    raise NameError("name 'DeepAnalysisRunner' is not defined")
  except NameError as exc:
    message = format_user_error(exc)

  assert "DeepAnalysisRunner" not in message
  assert "Перезапустите" in message or "ошибка" in message.lower()


def test_format_user_error_passes_mix_generator_errors():
  from engine.mix_generator.mix_generator import MixGeneratorError

  message = format_user_error(MixGeneratorError("Нет треков с BPM"))
  assert message == "Нет треков с BPM"
