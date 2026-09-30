import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from buddy.commands import Action, execute, parse


@pytest.mark.parametrize(
    "said,url_part",
    [
        ("open youtube", "youtube.com"),
        ("youtube open kar de", "youtube.com"),
        ("YouTube kholo", "youtube.com"),
        ("यूट्यूब ओपन कर दे", "youtube.com"),
        ("please open gmail", "mail.google.com"),
        ("open github.com", "github.com"),
    ],
)
def test_open_sites(said, url_part):
    a = parse(said)
    assert a.kind == "open_url" and url_part in a.args["url"]


@pytest.mark.parametrize("said,app", [("open notepad", "notepad"), ("calculator kholo", "calculator"), ("open vlc", "vlc")])
def test_open_apps(said, app):
    a = parse(said)
    assert a.kind == "open_app" and a.args["name"] == app


@pytest.mark.parametrize(
    "said,name",
    [
        ("create folder named chandan", "Chandan"),
        ("create a folder called chandan", "Chandan"),
        ("folder create kar de chandan ke naam se", "Chandan"),
        ("chandan ke naam se folder banao", "Chandan"),
        ("चंदन के नाम से फोल्डर बनाओ", "चंदन"),
        ("make folder chandan", "Chandan"),
    ],
)
def test_create_folder(said, name):
    a = parse(said)
    assert a.kind == "create_folder" and a.args["name"] == name


def test_create_folder_executes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Desktop").mkdir()
    msg = execute(parse("create folder named chandan"))
    assert (tmp_path / "Desktop" / "Chandan").is_dir()
    assert "Chandan" in msg


def test_folder_location():
    assert parse("create folder test in documents").args["location"] == "Documents"


def test_search_and_play():
    assert parse("search python tutorial").args["query"] == "python tutorial"
    a = parse("play arijit singh songs")
    assert a.kind == "open_url" and "arijit+singh+songs" in a.args["url"]


def test_misc():
    assert parse("what time is it").kind == "time"
    assert parse("tell me a joke").kind == "say"
    assert parse("volume up").args == {"dir": "up"}
    assert parse("bye").kind == "quit"
    assert parse("").kind == "unknown"
    assert parse("blah blah").kind == "unknown"
