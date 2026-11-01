import io
import urllib.error
from unittest import mock

import pytest

from scripts import wait_for_base_coverage as w


def response(status: int, payload: bytes):
    r = mock.MagicMock()
    r.__enter__.return_value.status = status
    r.__enter__.return_value.read.return_value = payload
    return r


def http_error(code: int, payload: bytes = b""):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(payload))


# _get_json


def test_get_json_uses_urlopen_by_default():
    with mock.patch("urllib.request.urlopen", return_value=response(200, b'{"a": 1}')) as urlopen:
        assert w._get_json("https://x/y", {"H": "v"}, 5) == (200, {"a": 1})
    req = urlopen.call_args.args[0]
    assert req.full_url == "https://x/y"
    assert req.get_header("Accept") == "application/json"
    assert req.get_header("H") == "v"
    assert urlopen.call_args.kwargs == {"timeout": 5}


def test_get_json_uses_given_opener():
    opener = mock.Mock()
    opener.open.return_value = response(200, b"[]")
    with mock.patch("urllib.request.urlopen") as urlopen:
        assert w._get_json("https://x", {}, 5, opener) == (200, [])
    urlopen.assert_not_called()


def test_get_json_returns_http_error_status_and_body():
    with mock.patch("urllib.request.urlopen", side_effect=http_error(404, b'{"detail": "no"}')):
        assert w._get_json("https://x", {}, 5) == (404, {"detail": "no"})


def test_get_json_non_json_body_is_none():
    with mock.patch("urllib.request.urlopen", return_value=response(200, b"<html>")):
        assert w._get_json("https://x", {}, 5) == (200, None)


# codecov_coverage


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ((200, {"totals": {"coverage": 91.5}}), (True, "coverage 91.5%")),
        ((404, None), (False, "no report yet")),
        ((500, None), (False, "HTTP 500")),
        ((200, {"totals": {"coverage": None}}), (False, "no coverage in report")),
        ((200, {"totals": None}), (False, "no coverage in report")),
        ((200, None), (False, "no coverage in report")),
    ],
)
def test_codecov_coverage(result, expected):
    with mock.patch.object(w, "_get_json", return_value=result) as get:
        assert w.codecov_coverage("o/r", "abc", 5) == expected
    assert get.call_args.args[0] == "https://api.codecov.io/api/v2/github/o/repos/r/totals/?sha=abc"
    assert get.call_args.args[1] == {}


def test_codecov_coverage_request_failure():
    with mock.patch.object(w, "_get_json", side_effect=urllib.error.URLError("down")):
        assert w.codecov_coverage("o/r", "abc", 5) == (False, "request failed: down")


# base_ci_state


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ((200, {"check_runs": []}), ("none", "no coverage check run")),
        ((200, {"check_runs": [{"id": 1, "status": "in_progress"}]}), ("running", "coverage in_progress")),
        (
            (200, {"check_runs": [{"id": 1, "status": "completed", "conclusion": "success"}]}),
            ("succeeded", "coverage success"),
        ),
        (
            (200, {"check_runs": [{"id": 1, "status": "completed", "conclusion": "skipped"}]}),
            ("failed", "coverage skipped"),
        ),
        (
            # The newest run wins.
            (
                200,
                {
                    "check_runs": [
                        {"id": 2, "status": "completed", "conclusion": "success"},
                        {"id": 1, "status": "completed", "conclusion": "failure"},
                    ]
                },
            ),
            ("succeeded", "coverage success"),
        ),
        ((403, {"message": "nope"}), ("running", "HTTP 403")),
        ((200, None), ("running", "HTTP 200")),
    ],
)
def test_base_ci_state(result, expected):
    with mock.patch.object(w, "_get_json", return_value=result) as get:
        assert w.base_ci_state("o/r", "abc", "coverage", "tok", 5) == expected
    url, headers, timeout, opener = get.call_args.args
    assert url == "https://api.github.com/repos/o/r/commits/abc/check-runs?check_name=coverage&filter=latest"
    assert headers["Authorization"] == "Bearer tok"
    # GitHub requests carry the token, so mustn't follow redirects.
    assert opener is w.github_opener


def test_base_ci_state_without_token():
    with mock.patch.object(w, "_get_json", return_value=(200, {"check_runs": []})) as get:
        w.base_ci_state("o/r", "abc", "coverage", None, 5)
    assert "Authorization" not in get.call_args.args[1]


def test_base_ci_state_request_failure():
    with mock.patch.object(w, "_get_json", side_effect=OSError("boom")):
        assert w.base_ci_state("o/r", "abc", "coverage", None, 5) == ("running", "request failed: boom")


# main


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run(monkeypatch, coverage, states, argv=()):
    """Run main() with codecov_coverage and base_ci_state answering from the given lists, one per attempt."""
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    coverage, states = iter(coverage), iter(states)
    calls = []

    def fake_state(repo, sha, check_name, token, timeout):
        calls.append((repo, sha, check_name, token))
        return next(states)

    monkeypatch.setattr(w, "codecov_coverage", lambda repo, sha, timeout: next(coverage))
    monkeypatch.setattr(w, "base_ci_state", fake_state)
    clock = FakeClock()
    w.main(["o/r", "abc", *argv], clock=clock, sleep=clock.sleep)
    return clock, calls


def test_main_returns_once_codecov_has_the_report(monkeypatch, capsys):
    clock, calls = run(
        monkeypatch,
        [(False, "no report yet"), (True, "coverage 90%")],
        [("running", "coverage in_progress")],
    )
    assert clock.now == 10
    assert calls == [("o/r", "abc", "coverage", "tok")]
    out = capsys.readouterr().out
    assert "Attempt 2: Codecov has the base report for abc (coverage 90%)" in out


def test_main_gives_up_at_once_when_base_ci_failed(monkeypatch, capsys):
    clock, _ = run(monkeypatch, [(False, "no report yet")], [("failed", "coverage failure")])
    assert clock.now == 0
    assert "::warning::Codecov has no coverage for base commit abc, whose CI didn't succeed" in capsys.readouterr().out


def test_main_gives_up_after_grace_once_base_ci_finished(monkeypatch, capsys):
    # Finished, re-run (which restarts the grace period), then finished for good.
    states = [("succeeded", "s"), ("running", "r")] + [("none", "n")] * 4
    clock, _ = run(monkeypatch, [(False, "x")] * 6, states, ["--grace", "30", "--check-name", "test"])
    assert clock.now == 50
    assert "whose CI has finished (n)" in capsys.readouterr().out


def test_main_gives_up_at_timeout(monkeypatch, capsys):
    clock, _ = run(monkeypatch, [(False, "x")] * 4, [("running", "r")] * 4, ["--timeout", "35"])
    assert clock.now == 30
    out = capsys.readouterr().out
    assert "::warning::Codecov still has no coverage for base commit abc after 35 seconds (r)" in out
