from exolot.annotations import annotation, escape_data, escape_property, warning


def finding(**extra):
    return {
        "path": "src/a.py",
        "line": 3,
        "column": 5,
        "endLine": 4,
        "endColumn": 9,
        "rule": "python:S1",
        "severity": "warning",
        "message": "bad",
        **extra,
    }


def test_escape_data_escapes_percent_and_newlines():
    assert escape_data("100% a\r\nb: c, d") == "100%25 a%0D%0Ab: c, d"


def test_escape_property_also_escapes_colons_and_commas():
    assert escape_property("100% a\nb: c, d") == "100%25 a%0Ab%3A c%2C d"


def test_annotation():
    assert annotation(finding()) == "::warning file=src/a.py,line=3,col=5,endLine=4,endColumn=9,title=python%3AS1::bad"


def test_annotation_command_follows_severity():
    commands = [annotation(finding(severity=s)).split()[0] for s in ("error", "warning", "info", "hint", "odd")]
    assert commands == ["::error", "::warning", "::notice", "::notice", "::warning"]


def test_annotation_escapes_path_and_message_and_uses_forward_slashes():
    line = annotation(finding(path="a,b\\c:d.py", message="x::y\n50%"))
    assert line.startswith("::warning file=a%2Cb/c%3Ad.py,")
    assert line.endswith("::x::y%0A50%25")


def test_annotation_without_end_position():
    line = annotation({k: v for k, v in finding().items() if k not in ("endLine", "endColumn")})
    assert "line=3,col=5,endLine=3,endColumn=5," in line


def test_warning_has_no_location():
    assert warning("30 C# files: not analyzed\n50%") == "::warning title=exolot::30 C# files: not analyzed%0A50%25"
