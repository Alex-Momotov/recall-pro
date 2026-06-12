from datetime import date

import pytest

from recallpro import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_add_and_get_item(conn):
    item_id = db.add_item(conn, "TCP/IP stack", date(2026, 6, 12))
    item = db.get_item(conn, item_id)
    assert item["title"] == "TCP/IP stack"
    assert item["learned_on"] == "2026-06-12"
    assert item["rung"] == 0
    assert item["next_due"] == "2026-06-13"
    assert item["gtask_id"] is None


def test_subpoints_roundtrip_and_replace(conn):
    item_id = db.add_item(conn, "Threads in Java", date(2026, 6, 12),
                          [(0, "Thread class"), (1, "run vs start"), (0, "Executors")])
    assert db.get_subpoints(conn, item_id) == [
        (0, "Thread class"), (1, "run vs start"), (0, "Executors")]
    db.set_subpoints(conn, item_id, [(0, "only one")])
    assert db.get_subpoints(conn, item_id) == [(0, "only one")]


def test_due_items_includes_overdue_excludes_future(conn):
    overdue = db.add_item(conn, "old", date(2026, 6, 1))
    due_today = db.add_item(conn, "fresh", date(2026, 6, 11))
    db.add_item(conn, "future", date(2026, 6, 12))  # due 6/13
    due = db.due_items(conn, date(2026, 6, 12))
    assert [i["id"] for i in due] == [overdue, due_today]


def test_complete_revision_advances_from_completion_date(conn):
    # learned Dec 31 → due Jan 1; postponed, completed Jan 3
    item_id = db.add_item(conn, "x", date(2025, 12, 31))
    item = db.get_item(conn, item_id)
    assert item["next_due"] == "2026-01-01"
    assert db.complete_revision(conn, item, date(2026, 1, 3)) is True
    item = db.get_item(conn, item_id)
    assert item["rung"] == 1
    # rung 1 gap is 3 days, counted from Jan 3 (not Jan 1)
    assert item["next_due"] == "2026-01-06"


def test_complete_revision_is_idempotent(conn):
    item_id = db.add_item(conn, "x", date(2026, 6, 11))
    item = db.get_item(conn, item_id)
    assert db.complete_revision(conn, item, date(2026, 6, 12)) is True
    # reprocessing the same due date (daemon crash/rerun) changes nothing
    assert db.complete_revision(conn, item, date(2026, 6, 14)) is False
    after = db.get_item(conn, item_id)
    assert after["rung"] == 1
    assert after["next_due"] == "2026-06-15"


def test_complete_revision_clears_gtask_id(conn):
    item_id = db.add_item(conn, "x", date(2026, 6, 11))
    db.set_gtask_id(conn, item_id, "task123")
    db.complete_revision(conn, db.get_item(conn, item_id), date(2026, 6, 12))
    assert db.get_item(conn, item_id)["gtask_id"] is None


def test_delete_cascades(conn):
    item_id = db.add_item(conn, "x", date(2026, 6, 11), [(0, "a")])
    db.complete_revision(conn, db.get_item(conn, item_id), date(2026, 6, 12))
    db.delete_item(conn, item_id)
    assert db.get_item(conn, item_id) is None
    assert conn.execute("SELECT COUNT(*) c FROM subpoints").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM revisions").fetchone()["c"] == 0


def test_find_by_title(conn):
    db.add_item(conn, "TCP/IP stack", date(2026, 6, 12))
    db.add_item(conn, "tcp/ip stack", date(2026, 6, 12))
    db.add_item(conn, "Java threads", date(2026, 6, 12))
    assert len(db.find_by_title_exact(conn, "TCP/IP STACK")) == 2
    assert len(db.find_by_title_substring(conn, "tcp")) == 2
    assert len(db.find_by_title_substring(conn, "thread")) == 1


def test_meta(conn):
    assert db.meta_get(conn, "k") is None
    db.meta_set(conn, "k", "v1")
    db.meta_set(conn, "k", "v2")
    assert db.meta_get(conn, "k") == "v2"
