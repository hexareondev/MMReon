"""Приём данных Game State Integration от клиента Dota 2.

На том же порту работает и «звонок» от второй копии MMReon: если программу запустили
ещё раз, новая копия просит уже работающую показать окно и сама закрывается.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMMAND_PATH = "/mmreon/"          # /mmreon/show — показать окно
MARKER = "X-MMReon"                # заголовок ответа: на порту работает именно MMReon


def start_server(port: int, token: str, on_state, on_command=None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if self.path.startswith(COMMAND_PATH):
                self._command(self.path[len(COMMAND_PATH):])
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                if payload.get("auth", {}).get("token") == token:
                    on_state(payload)
            except ValueError:
                pass
            except Exception as exc:  # не роняем сервер из-за одной ошибки
                print(f"[GSI] ошибка обработки: {exc!r}")
            self.send_response(200)
            self.end_headers()

        def _command(self, name: str):
            ok = self.headers.get("X-MMReon-Token") == token
            self.send_response(200 if ok else 403)
            self.send_header(MARKER, "1")
            self.end_headers()
            if ok and on_command:
                try:
                    on_command(name)
                except Exception as exc:
                    print(f"[команда] ошибка: {exc!r}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="gsi").start()
    return server


def ask_running(port: int, token: str, command: str = "show") -> str:
    """Спрашивает работающую копию на порту. Ответ:
    'ok' — это наш MMReon, команду принял; 'other_copy' — MMReon, но из другой папки (другой токен);
    'not_mmreon' — порт занят чем-то другим или никто не ответил."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{COMMAND_PATH}{command}", data=b"", method="POST",
                                 headers={"X-MMReon-Token": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # localhost — без прокси
    try:
        with opener.open(req, timeout=3) as resp:
            return "ok" if resp.headers.get(MARKER) else "not_mmreon"
    except urllib.error.HTTPError as exc:
        return "other_copy" if exc.headers.get(MARKER) else "not_mmreon"
    except (OSError, ValueError):
        return "not_mmreon"
