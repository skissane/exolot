"""A tiny LSP server for tests: answers initialize, asks the client for
configuration, and publishes one diagnostic per opened document."""

import json
import sys


def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode().partition(":")
        if name.lower() == "content-length":
            length = int(value)
    return json.loads(sys.stdin.buffer.read(length))


def send(msg):
    body = json.dumps(msg).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()


while (msg := read()) is not None:
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": 1000, "method": "workspace/configuration", "params": {"items": [{"section": "sonarlint", "scopeUri": "file:///w"}]}})
        reply = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}, "configReply": reply["result"]}})
    elif method == "textDocument/didOpen":
        doc = msg["params"]["textDocument"]
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "begin"}}})
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": doc["uri"], "diagnostics": []}})
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": doc["uri"], "diagnostics": [
            {"range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
             "severity": 2, "code": "fake:S1", "message": f"{doc['languageId']} issue"}]}})
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "end"}}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    elif method == "exit":
        break
    elif method == "boom":
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -1, "message": "boom"}})
