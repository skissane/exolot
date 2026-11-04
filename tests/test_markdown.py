from typing import Any

import pytest

from exolot import markdown
from exolot.markdown import check_link_template, escape, findings_table, link, statistics_table


def finding(
    path: str = "src/a.py", line: int = 3, rule: str = "python:S1", message: str = "bad", **extra: object
) -> dict[str, Any]:
    return {"path": path, "line": line, "column": 5, "rule": rule, "severity": "warning", "message": message, **extra}


def test_escape_puts_text_on_one_line_and_escapes_markdown() -> None:
    assert escape("a | b `c` <d>\nnext *e* &amp; [f](g) _h_ ~i~ \\") == (
        "a \\| b \\`c\\` \\<d\\> next \\*e\\* \\&amp; \\[f\\](g) \\_h\\_ \\~i\\~ \\\\"
    )


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ('Add the "@Override" annotation', 'Add the "@\u200bOverride" annotation'),
        ("@staticmethod, see #12 and org/repo#3", "@\u200bstaticmethod, see #\u200b12 and org/repo#\u200b3"),
        ("node_modules/@types/a.ts:1", "node\\_modules/@\u200btypes/a.ts:1"),
        # Neither a mention nor a reference, so left alone.
        ("a @ b, C# #define, dev@example.com", "a @ b, C# #define, dev@example.com"),
    ],
)
def test_escape_stops_mentions_and_references(text: str, escaped: str) -> None:
    assert escape(text) == escaped


def test_comment_doesnt_mention_annotations_in_messages() -> None:
    body = markdown.comment([finding(message='Add the "@Override" annotation')])
    assert "@Override" not in body
    assert "@\u200bOverride" in body


def test_findings_table_without_links() -> None:
    assert findings_table([finding(), finding(path="tests\\b_c.py", line=1, message="x|y")]) == [
        "| Location | Rule | Message |",
        "| --- | --- | --- |",
        "| src/a.py:3 | python:S1 | bad |",
        "| tests/b\\_c.py:1 | python:S1 | x\\|y |",
    ]


def test_findings_table_with_links() -> None:
    rows = findings_table(
        [finding(endLine=4, endColumn=9)], "https://x/{path}?l={line}&c={column}-{end_line}.{end_column}"
    )
    assert rows[2] == "| [src/a.py:3](https://x/src/a.py?l=3&c=5-4.9) | python:S1 | bad |"


def test_link_quotes_the_path_and_defaults_the_end() -> None:
    f = finding(path="a) [x](https://evil.example).py")
    assert link("{path}#L{end_line}:{end_column}", f) == "a%29%20%5Bx%5D%28https%3A//evil.example%29.py#L3:5"


@pytest.mark.parametrize(
    ("template", "error"),
    [
        ("", "empty link template"),
        ("{nope}", "unknown field 'nope'"),
        ("{path", "bad link template"),
        ("{0}", "bad link template"),
        ("{path.foo}", "bad link template"),
        ("{line[0]}", "bad link template"),
    ],
)
def test_check_link_template_rejects_bad_templates(template: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        check_link_template(template)


def test_check_link_template_accepts_good_ones() -> None:
    assert check_link_template("u/{path}#L{line}") == "u/{path}#L{line}"


def test_statistics_table() -> None:
    assert statistics_table([("python:S1", 2), ("x:S_2", 1)], {"python:S1": "Rule <one>"}) == [
        "| Count | Rule | Name |",
        "| ---: | --- | --- |",
        "| 2 | python:S1 | Rule \\<one\\> |",
        "| 1 | x:S\\_2 |  |",
    ]


def test_changed_findings_sections() -> None:
    findings = [
        {"path": "a.py", "line": 1, "column": 1, "rule": "r", "message": "m", "changed": True},
        {"path": "b.py", "line": 2, "column": 1, "rule": "r", "message": "m", "changed": False},
    ]
    assert markdown.changed_findings_sections(findings, heading="New") == [
        "### New (1)",
        "",
        "| Location | Rule | Message |",
        "| --- | --- | --- |",
        "| a.py:1 | r | m |",
        "",
        "<details>",
        "<summary>Elsewhere (1)</summary>",
        "",
        "| Location | Rule | Message |",
        "| --- | --- | --- |",
        "| b.py:2 | r | m |",
        "",
        "</details>",
    ]
    assert markdown.changed_findings_sections(findings[:1]) == [
        "### On changed lines (1)",
        "",
        "| Location | Rule | Message |",
        "| --- | --- | --- |",
        "| a.py:1 | r | m |",
    ]


def test_comment_without_findings() -> None:
    assert markdown.comment([]) == "## exolot's findings\n\nNo issues found.\n"


def test_comment_lists_all_findings_with_a_count() -> None:
    body = markdown.comment([finding(line=3), finding(line=9)], preamble="  Read *this*.\n")
    assert body.startswith("## exolot's findings\n\nRead *this*.\n\n### Findings (2)\n\n| Location |")
    assert "<details>" not in body


def test_comment_puts_changed_lines_first_and_links() -> None:
    body = markdown.comment(
        [finding(line=3, changed=True), finding(line=9, changed=False)],
        link_template="https://x/{path}#L{line}",
        changed=True,
        commit="abc",
        run_url="https://run",
    )
    new, old = body.split("<details>")
    assert "Analysis of abc, from [this workflow run](https://run).\n" in new
    assert "### On changed lines (1)" in new
    assert "[src/a.py:3](https://x/src/a.py#L3)" in new
    assert "Elsewhere (1)" in old
    assert "[src/a.py:9](https://x/src/a.py#L9)" in old


def test_comment_names_the_commit_without_a_run() -> None:
    body = markdown.comment([], commit="abc")
    assert "Analysis of abc.\n" in body
    assert "workflow run" not in body


def test_comment_ignores_a_blank_preamble() -> None:
    assert markdown.comment([], preamble=" \n") == markdown.comment([])


@pytest.mark.parametrize("run_url", [None, "https://run"])
def test_comment_is_truncated_to_fit(run_url: str | None) -> None:
    body = markdown.comment([finding(line=n, message="x" * 500) for n in range(1, 200)], run_url=run_url)
    assert len(body) <= markdown.MAX_COMMENT_CHARS + 200
    assert body.endswith("._\n")
    assert "Report truncated" in body
    assert ("[this workflow run](https://run)" in body.rsplit("\n\n", 1)[1]) == bool(run_url)


def test_comment_closes_a_truncated_elsewhere_section() -> None:
    findings = [finding(line=1, changed=True)] + [finding(line=n, message="x" * 500) for n in range(2, 200)]
    body = markdown.comment(findings, changed=True)
    assert body.count("<details>") == body.count("</details>") == 1
    assert body.index("</details>") < body.index("Report truncated")
