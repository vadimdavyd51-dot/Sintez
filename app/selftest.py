"""Самопроверка: озвучивает короткий текст целиком (на процессоре), проверяет файл и проверку на слух.
Запускается при сборке; у пользователя не нужна."""
import os, shutil, sys, threading
APP = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(APP, "models"))
os.environ["PYTHONUTF8"] = "1"
from engine import Engine, OUT_ROOT

logs = []
e = Engine(lambda m: (logs.append(str(m)), print(m, flush=True)))
text = "Садись поближе к огню.\nЯ расскажу тебе одну историю. Только не оглядывайся!"
final = e.run(text, {"project": "selftest", "nfe": 16, "check": True, "check_tries": 2}, lambda ev: None, threading.Event())
assert final and os.path.getsize(final) > 100_000, "итоговый файл не создан"
assert any("Проверка озвучки на слух: включена" in l for l in logs), "проверка на слух не включилась"
assert any("основной, напряжённый, тихий" in l for l in logs), "образцы голоса не подключились"
size = os.path.getsize(final)
shutil.rmtree(os.path.join(OUT_ROOT, "selftest"), ignore_errors=True)
print("SELFTEST OK", size, "байт")
