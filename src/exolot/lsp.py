"""Minimal synchronous JSON-RPC/LSP client over a subprocess's stdio.

A background thread reads messages from the server. Responses resolve the
matching pending request; server-initiated requests and notifications are
dispatched to registered handlers. Server requests with no handler are
answered with ``null`` so the server never blocks waiting on us.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import IO, Any

log = logging.getLogger(__name__)

Handler = Callable[[Any], Any]


class LspError(Exception):
    def __init__(self, error: dict[str, Any]):
        super().__init__(f"{error.get('code')}: {error.get('message')}")
        self.error = error


class LspClient:
    def __init__(self, proc: subprocess.Popen[bytes]):
        assert proc.stdin is not None and proc.stdout is not None
        self._proc = proc
        self._stdin: IO[bytes] = proc.stdin
        self._stdout: IO[bytes] = proc.stdout
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, Future[Any]] = {}
        self._pending_lock = threading.Lock()
        self._request_handlers: dict[str, Handler] = {}
        self._notification_handlers: dict[str, Handler] = {}
        self._reader = threading.Thread(target=self._read_loop, name="lsp-reader", daemon=True)
        self.closed = threading.Event()

    def start(self) -> None:
        self._reader.start()

    def close(self) -> None:
        """Close the pipes to the server. Call this once the server has exited."""
        self._stdin.close()
        if self._reader.is_alive():
            self._reader.join()
        self._stdout.close()

    def on_request(self, method: str, handler: Handler) -> None:
        self._request_handlers[method] = handler

    def on_notification(self, method: str, handler: Handler) -> None:
        self._notification_handlers[method] = handler

    def request(self, method: str, params: Any = None) -> Future[Any]:
        with self._pending_lock:
            self._next_id += 1
            msg_id = self._next_id
            future: Future[Any] = Future()
            self._pending[msg_id] = future
        self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        return future

    def notify(self, method: str, params: Any = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        log.debug("-> %s", body[:2000])
        with self._write_lock:
            self._stdin.write(header + body)
            self._stdin.flush()

    def _read_message(self) -> dict[str, Any] | None:
        length = None
        while True:
            line = self._stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            name, _, value = line.decode("ascii").partition(":")
            if name.strip().lower() == "content-length":
                length = int(value.strip())
        if length is None:
            raise ValueError("LSP message without Content-Length header")
        body = self._stdout.read(length)
        if len(body) < length:
            return None
        log.debug("<- %s", body[:2000])
        return json.loads(body)

    def _read_loop(self) -> None:
        try:
            while (message := self._read_message()) is not None:
                self._dispatch(message)
        except Exception:
            log.exception("LSP reader failed")
        finally:
            self.closed.set()
            with self._pending_lock:
                pending, self._pending = self._pending, {}
            for future in pending.values():
                if future.set_running_or_notify_cancel():
                    future.set_exception(ConnectionError("language server closed the connection"))

    def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method is None:
            with self._pending_lock:
                future = self._pending.pop(message.get("id"), None)
            if future is None:
                log.warning("response for unknown request id %r", message.get("id"))
            elif not future.set_running_or_notify_cancel():
                log.debug("dropping response to cancelled request %r", message.get("id"))
            elif "error" in message:
                future.set_exception(LspError(message["error"]))
            else:
                future.set_result(message.get("result"))
        elif "id" in message:
            self._handle_server_request(message["id"], method, message.get("params"))
        else:
            handler = self._notification_handlers.get(method)
            if handler is None:
                log.debug("unhandled notification %s", method)
                return
            try:
                handler(message.get("params"))
            except Exception:
                log.exception("notification handler for %s failed", method)

    def _handle_server_request(self, msg_id: Any, method: str, params: Any) -> None:
        handler = self._request_handlers.get(method)
        if handler is None:
            log.debug("unhandled server request %s, replying null", method)
            result = None
        else:
            try:
                result = handler(params)
            except Exception as e:
                log.exception("request handler for %s failed", method)
                self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}})
                return
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})
