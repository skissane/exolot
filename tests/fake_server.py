"""A tiny LSP server for tests: answers initialize, asks the client for
configuration, and publishes one diagnostic per opened document."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

RULES_FAIL = os.environ.get("FAKE_SERVER_RULES_FAIL") == "1"
CODE_ACTIONS_FAIL = os.environ.get("FAKE_SERVER_CODE_ACTIONS_FAIL") == "1"


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
        send(
            {
                "jsonrpc": "2.0",
                "id": 1000,
                "method": "workspace/configuration",
                "params": {"items": [{"section": "sonarlint", "scopeUri": "file:///w"}]},
            }
        )
        reply = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}, "configReply": reply["result"]}})
    elif method == "textDocument/didOpen":
        doc = msg["params"]["textDocument"]
        if "SILENT" in doc["text"]:
            continue
        if "CRASH" in doc["text"]:
            sys.exit(1)
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "begin"}}})
        if "BUSY" in doc["text"]:
            # Publish, but never end the progress, as if still analyzing.
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {"uri": doc["uri"], "diagnostics": []},
                }
            )
            continue
        send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": doc["uri"], "diagnostics": []},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": doc["uri"],
                    "diagnostics": [
                        {
                            "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
                            "severity": 2,
                            "code": "fake:S1",
                            "message": f"{doc['languageId']} issue",
                        }
                    ]
                    # One more issue for each "TWO" in the file, from a second rule.
                    + [
                        {
                            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                            "severity": 3,
                            "code": "fake:S2",
                            "message": "another issue",
                        }
                    ]
                    * doc["text"].count("TWO")
                    # And one with a secondary location for each "FLOW".
                    + [
                        {
                            "range": {"start": {"line": 0, "character": 1}, "end": {"line": 0, "character": 3}},
                            "severity": 1,
                            "code": "fake:S3",
                            "message": "flow issue [+1 location]",
                        }
                    ]
                    * doc["text"].count("FLOW"),
                },
            }
        )
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "end"}}})
    elif method == "sonarlint/listAllRules":
        if RULES_FAIL:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no such method"}})
        else:
            rules = {
                "Fake": [
                    {"key": "fake:S1", "name": "Fake rule one", "activeByDefault": True},
                    {"key": "fake:S2", "name": None},
                    {"bad": 1},
                ]
            }
            send({"jsonrpc": "2.0", "id": msg["id"], "result": rules})
    elif method == "textDocument/codeAction" and CODE_ACTIONS_FAIL:
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "no actions"}})
    elif method == "textDocument/codeAction":
        params = msg["params"]
        uri = params["textDocument"]["uri"]
        path = url2pathname(urlparse(uri).path)
        actions = [{"title": "Deactivate rule", "command": {"command": "SonarLint.DeactivateRule", "arguments": []}}]
        if "NOLOCATIONS" not in Path(path).read_text(encoding="utf-8", errors="replace"):
            location = {
                "textRange": {"startLine": 1, "startLineOffset": 4, "endLine": 1, "endLineOffset": 6},
                "uri": uri,
                "filePath": "/C:/not/used",  # as the server gives it on Windows
                "message": "the other one",
            }
            # One with no file, which means the issue's, and one with no range, which is skipped.
            elsewhere = {"textRange": {"startLine": 2, "startLineOffset": 0, "endLine": 2, "endLineOffset": 1}}
            flows = [{"locations": [location, {"uri": uri}]}, {"locations": [elsewhere]}]
            actions.append({"title": "Show all locations", "command": "SonarLint.ShowAllLocations"})
            actions.append(
                {
                    "title": "Show all locations",
                    "command": {"command": "SonarLint.ShowAllLocations", "arguments": [{"flows": flows}]},
                }
            )
        send({"jsonrpc": "2.0", "id": msg["id"], "result": actions})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    elif method == "exit":
        break
    elif method == "slow":
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "x", "value": {"kind": "begin"}}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": "late"})
    elif method == "boom":
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -1, "message": "boom"}})
