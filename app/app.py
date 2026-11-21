"""Рассказчик: локальное приложение озвучки. Открывает страницу в браузере на этом же компьютере."""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(APP_DIR, "models"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONUTF8", "1")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from engine import DEFAULTS, OUT_ROOT, Engine, Stopped, safe_name  # noqa: E402

PORT = int(os.environ.get("RASSKAZ_PORT", "7860"))


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.log = []
        self.parts = []
        self.running = False
        self.stop = threading.Event()
        self.final = None
        self.project = None
        self.chunk = None
        self.error = None
        self.engine = Engine(self.add_log)

    def add_log(self, line):
        with self.lock:
            self.log.append(time.strftime("%H:%M:%S ") + str(line))
            self.log = self.log[-400:]
        try:
            print(line)
        except Exception:
            pass

    def progress(self, ev):
        with self.lock:
            if ev["type"] == "parts":
                self.parts = ev["parts"]
            elif ev["type"] == "part":
                for p in self.parts:
                    if p["n"] == ev["n"]:
                        p["state"] = ev["state"]
                if ev["state"] != "work":
                    self.chunk = None
            elif ev["type"] == "chunk":
                self.chunk = ev

    def start(self, text, settings):
        with self.lock:
            if self.running:
                return False
            self.running, self.final, self.error, self.chunk = True, None, None, None
            self.stop.clear()
            self.project = safe_name(settings.get("project"))
        threading.Thread(target=self._work, args=(text, settings), daemon=True).start()
        return True

    def _work(self, text, settings):
        try:
            final = self.engine.run(text, settings, self.progress, self.stop)
            with self.lock:
                self.final = os.path.relpath(final, OUT_ROOT).replace("\\", "/") if final else None
            self.add_log("Готово." if final else "Готовых частей нет.")
        except Stopped:
            self.add_log("Остановлено. Готовые части сохранены: нажми «Озвучить», чтобы продолжить.")
        except Exception as e:
            with self.lock:
                self.error = repr(e)[:400]
            self.add_log("ОШИБКА: " + repr(e)[:400])
        finally:
            with self.lock:
                self.running = False

    def snapshot(self):
        with self.lock:
            return dict(running=self.running, log=self.log[-120:], parts=self.parts, final=self.final,
                        chunk=self.chunk, error=self.error, project=self.project)


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/":
            with open(os.path.join(APP_DIR, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/status":
            return self._send(200, STATE.snapshot())
        if path == "/defaults":
            return self._send(200, DEFAULTS)
        if path.startswith("/file/"):
            rel = path[len("/file/"):]
            full = os.path.abspath(os.path.join(OUT_ROOT, rel))
            if not full.startswith(os.path.abspath(OUT_ROOT) + os.sep) or not os.path.isfile(full):
                return self._send(404, {"error": "нет файла"})
            with open(full, "rb") as f:
                data = f.read()
            name = os.path.basename(full)
            return self._send(200, data, "audio/wav", {
                "Content-Disposition": "inline; filename*=UTF-8''" + name})
        self._send(404, {"error": "не найдено"})

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "плохой запрос"})
        if path == "/start":
            text = (data.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "Вставь текст для озвучки"})
            ok = STATE.start(text, data.get("settings") or {})
            return self._send(200 if ok else 409, {"ok": ok, "error": None if ok else "Озвучка уже идёт"})
        if path == "/stop":
            STATE.stop.set()
            return self._send(200, {"ok": True})
        if path == "/open":
            folder = os.path.join(OUT_ROOT, safe_name(data.get("project")))
            os.makedirs(folder, exist_ok=True)
            try:
                os.startfile(folder)  # только Windows
            except Exception:
                pass
            return self._send(200, {"ok": True, "folder": folder})
        self._send(404, {"error": "не найдено"})


def main():
    os.makedirs(OUT_ROOT, exist_ok=True)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Порт {PORT} занят: возможно, Рассказчик уже запущен. Открой http://127.0.0.1:{PORT}")
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        return
    url = f"http://127.0.0.1:{PORT}"
    print("Рассказчик запущен:", url)
    print("Это окно не закрывай, пока идёт озвучка. Чтобы выйти, закрой его.")
    if not os.environ.get("RASSKAZ_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
