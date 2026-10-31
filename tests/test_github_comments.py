import urllib.error
import urllib.request
from unittest import mock

import pytest

from scripts import github_comments
from scripts.github_comments import request


def response(payload: bytes):
    r = mock.MagicMock()
    r.__enter__.return_value.read.return_value = payload
    return r


def redirect(url, location):
    return urllib.error.HTTPError(url, 307, "Redirect", {"Location": location}, None)


def test_sends_json_with_token():
    with mock.patch("scripts.github_comments._opener.open", return_value=response(b'{"a": 1}')) as urlopen:
        result = request("POST", "https://api.github.com/x", "tok", json_body={"b": 2})
    assert result == {"a": 1}
    req = urlopen.call_args.args[0]
    assert urlopen.call_args.kwargs == {"timeout": 60}
    assert req.get_method() == "POST"
    assert req.data == b'{"b": 2}'
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("Authorization") == "Bearer tok"


def test_empty_response_is_none():
    with mock.patch("scripts.github_comments._opener.open", return_value=response(b"")):
        assert request("DELETE", "https://api.github.com/x", "tok") is None


def test_follows_redirects_dropping_token_off_host():
    responses = [
        redirect("https://uploads.github.com/a", "/b"),
        redirect("https://uploads.github.com/b", "https://elsewhere.example/c"),
        response(b'{"url": "u"}'),
    ]
    with mock.patch("scripts.github_comments._opener.open", side_effect=responses) as urlopen:
        result = request("POST", "https://uploads.github.com/a", "tok", data=b"png")
    assert result == {"url": "u"}
    sent = [c.args[0] for c in urlopen.call_args_list]
    assert [r.full_url for r in sent] == [
        "https://uploads.github.com/a",
        "https://uploads.github.com/b",
        "https://elsewhere.example/c",
    ]
    assert [r.data for r in sent] == [b"png"] * 3
    assert [r.get_header("Authorization") for r in sent] == ["Bearer tok", "Bearer tok", None]


def test_follows_get_redirects_itself():
    # As urlopen's default handler would, with the token, to any host.
    responses = [redirect("https://api.github.com/a", "https://elsewhere.example/b"), response(b"{}")]
    responses[0].code = 301
    with mock.patch("scripts.github_comments._opener.open", side_effect=responses) as urlopen:
        request("GET", "https://api.github.com/a", "tok")
    assert [c.args[0].get_header("Authorization") for c in urlopen.call_args_list] == ["Bearer tok", None]


def test_opener_does_not_follow_redirects():
    req = urllib.request.Request("https://api.github.com/a")
    assert github_comments._NoRedirects().redirect_request(req, None, 302, "Found", {}, "https://x.example/") is None


def test_too_many_redirects():
    with (
        mock.patch(
            "scripts.github_comments._opener.open", side_effect=[redirect("https://api.github.com/x", "/x")] * 5
        ),
        pytest.raises(RuntimeError, match="too many redirects"),
    ):
        request("GET", "https://api.github.com/x", "tok")


def test_other_errors_raised():
    error = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)
    with (
        error,
        mock.patch("scripts.github_comments._opener.open", side_effect=error),
        pytest.raises(urllib.error.HTTPError),
    ):
        request("GET", "https://api.github.com/x", "tok")


def test_upsert_reads_every_page_of_comments(monkeypatch):
    other = {"id": 1, "user": {"login": "someone"}, "body": "hi"}
    pages = {1: [other] * 100, 2: [{"id": 2, "user": {"login": "me"}, "body": "<!-- m -->\nold"}]}
    requests = []

    def fake_request(method, url, token, *, json_body=None, **kw):
        requests.append((method, url, json_body))
        return pages[int(url.rsplit("page=", 1)[1])] if method == "GET" else None

    monkeypatch.setattr(github_comments, "request", fake_request)
    github_comments.upsert_comment("o/r", 7, "me", "<!-- m -->", "<!-- m -->\nnew", "tok")
    assert [r[0] for r in requests] == ["GET", "GET", "PATCH"]
    assert requests[-1][1:] == ("https://api.github.com/repos/o/r/issues/comments/2", {"body": "<!-- m -->\nnew"})
