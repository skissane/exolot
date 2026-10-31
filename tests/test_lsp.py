import subprocess
import sys
from pathlib import Path

import pytest

from exolot.lsp import LspClient, LspError

FAKE_SERVER = Path(__file__).with_name("fake_server.py")


@pytest.fixture
def client():
    proc = subprocess.Popen([sys.executable, str(FAKE_SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    c = LspClient(proc)
    yield c
    proc.kill()
    proc.wait()
    c.close()


def test_answers_server_requests_during_a_request(client):
    client.on_request("workspace/configuration", lambda params: [{"answered": params["items"][0]["section"]}])
    client.start()
    result = client.request("initialize", {}).result(timeout=10)
    assert result["configReply"] == [{"answered": "sonarlint"}]


def test_unhandled_server_request_gets_null(client):
    client.start()
    result = client.request("initialize", {}).result(timeout=10)
    assert result["configReply"] is None


def test_error_response_raises(client):
    client.start()
    with pytest.raises(LspError, match="boom"):
        client.request("boom").result(timeout=10)


def test_response_to_cancelled_request_is_dropped(client):
    notes = []
    client.on_notification("$/progress", notes.append)
    future = client.request("slow")
    assert future.cancel()
    client.start()
    # The reader must survive the response to the cancelled request.
    assert client.request("initialize", {}).result(timeout=10) is not None
    assert notes
