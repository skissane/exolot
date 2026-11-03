import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from exolot.lsp import LspClient, LspError

FAKE_SERVER = Path(__file__).with_name("fake_server.py")


@pytest.fixture
def client() -> Iterator[LspClient]:
    proc = subprocess.Popen([sys.executable, str(FAKE_SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    c = LspClient(proc)
    yield c
    proc.kill()
    proc.wait()
    c.close()


def test_answers_server_requests_during_a_request(client: LspClient) -> None:
    client.on_request("workspace/configuration", lambda params: [{"answered": params["items"][0]["section"]}])
    client.start()
    result = client.request("initialize", {}).result(timeout=10)
    assert result["configReply"] == [{"answered": "sonarlint"}]


def test_unhandled_server_request_gets_null(client: LspClient) -> None:
    client.start()
    result = client.request("initialize", {}).result(timeout=10)
    assert result["configReply"] is None


def test_error_response_raises(client: LspClient) -> None:
    client.start()
    future = client.request("boom")
    with pytest.raises(LspError, match="boom"):
        future.result(timeout=10)


def test_response_to_cancelled_request_is_dropped(client: LspClient) -> None:
    notes: list[object] = []
    client.on_notification("$/progress", notes.append)
    future = client.request("slow")
    assert future.cancel()
    client.start()
    # The reader must survive the response to the cancelled request.
    assert client.request("initialize", {}).result(timeout=10) is not None
    assert notes


@pytest.mark.parametrize("request_id", [True, 99, "1", None])
def test_response_with_unknown_id_is_ignored(
    client: LspClient, caplog: pytest.LogCaptureFixture, request_id: object
) -> None:
    future = client.request("slow")  # id 1; the reader isn't started, so no response arrives
    client._dispatch({"jsonrpc": "2.0", "id": request_id, "result": "wrong"})
    assert not future.done()
    assert f"response for unknown request id {request_id!r}" in caplog.text


def test_request_after_the_server_closed_fails_at_once(client: LspClient) -> None:
    client.start()
    client.notify("exit")
    assert client.closed.wait(timeout=10)
    future = client.request("initialize", {})
    with pytest.raises(ConnectionError):
        future.result(timeout=0)


def test_writing_to_a_dead_server_is_logged_not_raised(client: LspClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="exolot.lsp")
    client.start()
    client.notify("exit")
    assert client.closed.wait(timeout=10)
    client._proc.wait(timeout=10)
    client.notify("x" * 1_000_000)  # more than the pipe holds, so the write fails
    client.close()
    assert "LSP writer failed" in caplog.text
