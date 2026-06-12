"""Keystroke-level tests of the capture window via prompt_toolkit pipe input.

Key encoding: Enter = \\r, Tab = \\t, Ctrl-D = \\x04 (exit; same handler
as Esc — a lone ESC needs a flush timeout that pipe-input EOF would beat).

Flow under test: free multi-line editing with manual '- ' hyphens; Enter on
an empty line finalizes and saves the current item; exit saves in-progress.
"""
from datetime import date

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from recallpro import db, tui


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def capture(conn, keys: str) -> None:
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        tui.run_capture(conn, input=pipe, output=DummyOutput())


def test_blank_line_saves_item_with_manual_hyphens(conn):
    capture(conn, "Threads in Java\r"
                  "- Thread class\r"
                  "  - run vs start\r"
                  "- Executors\r"
                  "\r"            # Enter on empty line → save
                  "\x04")
    items = db.list_items(conn)
    assert len(items) == 1
    assert items[0]["title"] == "Threads in Java"
    assert db.get_subpoints(conn, items[0]["id"]) == [
        (0, "Thread class"), (1, "run vs start"), (0, "Executors")]
    assert items[0]["learned_on"] == date.today().isoformat()


def test_double_enter_saves_title_only_item(conn):
    capture(conn, "Quick item\r\r\x04")
    items = db.list_items(conn)
    assert len(items) == 1
    assert items[0]["title"] == "Quick item"
    assert db.get_subpoints(conn, items[0]["id"]) == []


def test_multiple_items_in_one_session(conn):
    capture(conn, "First\r\r" "Second\r- detail\r\r" "\x04")
    items = db.list_items(conn)
    assert [i["title"] for i in items] == ["First", "Second"]
    assert db.get_subpoints(conn, items[1]["id"]) == [(0, "detail")]


def test_exit_saves_in_progress_item(conn):
    # exit without the finalizing blank line: nothing typed may be lost
    capture(conn, "Unfinished\r- some bullet\x04")
    items = db.list_items(conn)
    assert len(items) == 1
    assert items[0]["title"] == "Unfinished"
    assert db.get_subpoints(conn, items[0]["id"]) == [(0, "some bullet")]


def test_exit_on_empty_window_saves_nothing(conn):
    capture(conn, "\x04")
    assert db.list_items(conn) == []


def test_extra_enters_between_items_are_harmless(conn):
    capture(conn, "Only item\r\r\r\r\x04")
    assert [i["title"] for i in db.list_items(conn)] == ["Only item"]


def test_quotes_and_apostrophes_are_fine(conn):
    capture(conn, "What's a \"mutex\"?\r\r\x04")
    assert db.list_items(conn)[0]["title"] == 'What\'s a "mutex"?'


def test_tab_indentation_counts_as_a_level(conn):
    capture(conn, "T\r- a\r\t- b\r\r\x04")
    items = db.list_items(conn)
    assert db.get_subpoints(conn, items[0]["id"]) == [(0, "a"), (1, "b")]
