import pytest

from exolot.markdown import check_link_template, escape, findings_table, link, statistics_table


def finding(path="src/a.py", line=3, rule="python:S1", message="bad", **extra):
    return {"path": path, "line": line, "column": 5, "rule": rule, "severity": "warning", "message": message, **extra}


def test_escape_puts_text_on_one_line_and_escapes_markdown():
    assert escape("a | b `c` <d>\nnext *e* &amp; [f](g) _h_ ~i~ \\") == (
        "a \\| b \\`c\\` \\<d\\> next \\*e\\* \\&amp; \\[f\\](g) \\_h\\_ \\~i\\~ \\\\"
    )


def test_findings_table_without_links():
    assert findings_table([finding(), finding(path="tests\\b_c.py", line=1, message="x|y")]) == [
        "| Location | Rule | Message |",
        "| --- | --- | --- |",
        "| src/a.py:3 | python:S1 | bad |",
        "| tests/b\\_c.py:1 | python:S1 | x\\|y |",
    ]


def test_findings_table_with_links():
    rows = findings_table(
        [finding(endLine=4, endColumn=9)], "https://x/{path}?l={line}&c={column}-{end_line}.{end_column}"
    )
    assert rows[2] == "| [src/a.py:3](https://x/src/a.py?l=3&c=5-4.9) | python:S1 | bad |"


def test_link_quotes_the_path_and_defaults_the_end():
    f = finding(path="a) [x](https://evil.example).py")
    assert link("{path}#L{end_line}:{end_column}", f) == "a%29%20%5Bx%5D%28https%3A//evil.example%29.py#L3:5"


@pytest.mark.parametrize(
    ("template", "error"),
    [("{nope}", "unknown field 'nope'"), ("{path", "bad link template"), ("{0}", "bad link template")],
)
def test_check_link_template_rejects_bad_templates(template, error):
    with pytest.raises(ValueError, match=error):
        check_link_template(template)


def test_check_link_template_accepts_good_ones():
    assert check_link_template("u/{path}#L{line}") == "u/{path}#L{line}"


def test_statistics_table():
    assert statistics_table([("python:S1", 2), ("x:S_2", 1)], {"python:S1": "Rule <one>"}) == [
        "| Count | Rule | Name |",
        "| ---: | --- | --- |",
        "| 2 | python:S1 | Rule \\<one\\> |",
        "| 1 | x:S\\_2 |  |",
    ]
