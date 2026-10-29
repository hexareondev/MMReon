"""Приём данных Game State Integration от клиента Dota 2."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_server(port: int, token: str, on_state) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
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

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="gsi").start()
    return server
