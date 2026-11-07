"""A tiny LSP server for tests: answers initialize, asks the client for
configuration, and publishes one diagnostic per opened document."""

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from exolot.jsontypes import is_json_object

RULES_FAIL = os.environ.get("FAKE_SERVER_RULES_FAIL") == "1"
CODE_ACTIONS_FAIL = os.environ.get("FAKE_SERVER_CODE_ACTIONS_FAIL") == "1"
# The plugin states to report, as JSON: {"plugin name": state}, or "fail" to fail.
PLUGIN_STATES = os.environ.get("FAKE_SERVER_PLUGIN_STATES", "{}")

# How the real server logs a sensor's failure: its name, then the stack trace.
SENSOR_FAILURE = [
    "[Error - 01:02:03.004] [sonarlint : sonarlint-analysis-scheduler] Error executing sensor: 'OmniSharp'",
    "[Error - 01:02:03.004] [sonarlint : sonarlint-analysis-scheduler] java.lang.IllegalStateException: "
    "Unable to start OmniSharp\n\tat org.sonarsource.Sensor.execute(Sensor.java:100)\n"
    'Caused by: java.io.IOException: Cannot run program "dotnet": Exec failed, error: 2\n\tat java.base/X.start\n'
    "Caused by: java.io.IOException: Exec failed, error: 2\n\tat java.base/Y.forkAndExec\n\t... 28 more",
]


def read() -> dict[str, Any] | None:
    length = -1  # read everything if there's no Content-Length
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
    data = json.loads(sys.stdin.buffer.read(length))
    assert is_json_object(data)
    return data


def send(msg: object) -> None:
    body = json.dumps(msg).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()


def log(message: str) -> None:
    send({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"type": 4, "message": message}})


# Set by initialize, which the client always sends before didOpen.
rules_off: set[str] = set()

while (msg := read()) is not None:
    method = msg.get("method")
    if method == "initialize":
        # Like the real server: every message has type Log, with its level in
        # the text, and Debug messages only with verbose logs.
        if msg["params"].get("initializationOptions", {}).get("showVerboseLogs"):
            log("[Debug - 01:02:03.004] a debug message")
        log("[Info - 01:02:03.004] an info message")
        log("[Warn - 01:02:03.004] a warning message")
        log("[Error - 01:02:03.004] an error message\n\tat its.stack.Trace")
        log("[Fancy - 01:02:03.004] a message at an unknown level")
        log("a message with no level")
        print("fake server stderr", file=sys.stderr, flush=True)
        if home := os.environ.get("SONARLINT_USER_HOME"):
            # Like the real server, keep state in its home (but never in ~/.sonarlint).
            (Path(home) / "storage").mkdir(exist_ok=True)
            (Path(home) / "storage" / "state").write_text("fake server state\n")
            # And an analyzer it downloaded.
            plugin = Path(home) / "storage" / "ondemand-plugins" / "fake" / "1.0"
            plugin.mkdir(parents=True, exist_ok=True)
            (plugin / "sonar-fake-plugin-1.0.jar").write_text("fake plugin\n")
        send(
            {
                "jsonrpc": "2.0",
                "id": 1000,
                "method": "workspace/configuration",
                "params": {"items": [{"section": "sonarlint", "scopeUri": "file:///w"}]},
            }
        )
        reply = read()
        assert reply is not None
        # Like the real server, report no issues from rules the settings turn
        # off. (Tests of the LSP client alone answer with no settings.)
        settings: dict[str, Any] = reply["result"][0] if reply["result"] else {}
        rules: dict[str, dict[str, Any]] = settings.get("rules", {})
        rules_off = {key for key, setting in rules.items() if setting.get("level") == "off"}
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}, "configReply": reply["result"]}})
    elif method == "textDocument/didOpen":
        doc = msg["params"]["textDocument"]
        if "SILENT" in doc["text"]:
            continue
        if "CRASH" in doc["text"]:
            sys.exit(1)
        if "DEAF" in doc["text"]:
            # Never read again, so the client's writes to us block once the
            # pipe is full. The test kills us.
            threading.Event().wait()
        if "CHATTY" in doc["text"]:
            # Like the real server with verbose logs: a request the client must
            # answer and lots of log output for every file, written without
            # reading anything, so the client must keep reading while it writes.
            send(
                {
                    "jsonrpc": "2.0",
                    "id": f"open-{doc['uri']}",
                    "method": "sonarlint/isOpenInEditor",
                    "params": doc["uri"],
                }
            )
            log("[Debug - 01:02:03.004] " + "x" * 50_000)
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "begin"}}})
        if "SENSORFAIL" in doc["text"]:
            for message in SENSOR_FAILURE:
                log(message)
        if "NEEDCDB" in doc["text"]:
            send({"jsonrpc": "2.0", "method": "sonarlint/needCompilationDatabase"})
        if "SHOWMSG" in doc["text"]:
            for kind in (1, 3, 2):
                message = f"message\n::of type {kind}" if kind != 2 else " "  # an empty one is ignored
                send({"jsonrpc": "2.0", "method": "window/showMessage", "params": {"type": kind, "message": message}})
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
                        diagnostic
                        for diagnostic in [
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
                        * doc["text"].count("FLOW")
                        if diagnostic["code"] not in rules_off
                    ],
                },
            }
        )
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "t", "value": {"kind": "end"}}})
    elif method == "sonarlint/listAllRules":
        if RULES_FAIL:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no such method"}})
        else:
            rules_list = {
                "Fake": [
                    {"key": "fake:S1", "name": "Fake rule one", "activeByDefault": True},
                    {"key": "fake:S2", "name": None},
                    {"bad": 1},
                ]
            }
            send({"jsonrpc": "2.0", "id": msg["id"], "result": rules_list})
    elif method == "textDocument/codeAction" and CODE_ACTIONS_FAIL:
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "no actions"}})
    elif method == "textDocument/codeAction":
        params = msg["params"]
        uri: str = params["textDocument"]["uri"]
        path = url2pathname(urlparse(uri).path)
        actions: list[dict[str, Any]] = [
            {
                "title": "Deactivate rule",
                "command": {"command": "SonarLint.DeactivateRule", "arguments": []},
            }
        ]
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
    elif method == "sonarlint/getPluginStatuses":
        if PLUGIN_STATES == "fail":
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no such method"}})
        else:
            statuses = [{"pluginName": name, "state": state} for name, state in json.loads(PLUGIN_STATES).items()]
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"pluginStatuses": statuses}})
    elif method == "shutdown":
        # Like the real server, which logs errors such as ClosedSelectorException as it shuts down.
        log("[Error - 01:02:03.004] after shutdown")
        send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    elif method == "exit":
        break
    elif method == "slow":
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"token": "x", "value": {"kind": "begin"}}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": "late"})
    elif method == "boom":
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -1, "message": "boom"}})
