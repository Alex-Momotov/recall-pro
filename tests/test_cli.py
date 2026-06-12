from datetime import date

import pytest

from recallpro.cli import parse_capture_args, parse_date

TODAY = date(2026, 6, 12)


def test_words_joined_no_quotes_needed():
    title, learned = parse_capture_args(["TCP/IP", "stack"], TODAY)
    assert title == "TCP/IP stack"
    assert learned == TODAY


def test_on_iso_date():
    title, learned = parse_capture_args(["x", "--on", "2026-06-10"], TODAY)
    assert (title, learned) == ("x", date(2026, 6, 10))


def test_on_equals_form_and_position():
    title, learned = parse_capture_args(["--on=yesterday", "a", "b"], TODAY)
    assert (title, learned) == ("a b", date(2026, 6, 11))


def test_future_date_rejected():
    with pytest.raises(ValueError):
        parse_capture_args(["x", "--on", "2026-06-13"], TODAY)


def test_empty_title_rejected():
    with pytest.raises(ValueError):
        parse_capture_args(["--on", "yesterday"], TODAY)


def test_on_requires_value():
    with pytest.raises(ValueError):
        parse_capture_args(["x", "--on"], TODAY)


def test_sync_is_reserved_and_dispatches_to_daemon(monkeypatch, tmp_path):
    from recallpro import cli, daemon, db
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(cli.db, "connect", lambda: conn)
    seen = {}
    monkeypatch.setattr(daemon, "run_cycle", lambda c: seen.update(conn=c) or True)
    assert cli.main(["sync"]) == 0
    assert seen["conn"] is conn


def test_delete_accepts_multiple_ids(monkeypatch, tmp_path):
    from recallpro import cli, db
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(cli.db, "connect", lambda: conn)
    a = db.add_item(conn, "a", TODAY)
    b = db.add_item(conn, "b", TODAY)
    c = db.add_item(conn, "c", TODAY)
    assert cli.main(["delete", str(a), str(c)]) == 0
    assert [i["id"] for i in db.list_items(conn)] == [b]


def test_delete_missing_id_reports_but_deletes_rest(monkeypatch, tmp_path):
    from recallpro import cli, db
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(cli.db, "connect", lambda: conn)
    a = db.add_item(conn, "a", TODAY)
    assert cli.main(["delete", str(a), "999"]) == 1
    assert db.list_items(conn) == []


def test_parse_date_keywords():
    assert parse_date("today", TODAY) == TODAY
    assert parse_date("Yesterday", TODAY) == date(2026, 6, 11)
    with pytest.raises(ValueError):
        parse_date("not-a-date", TODAY)
