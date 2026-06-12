from datetime import date

import pytest

from recallpro import daemon, db

TODAY = date(2026, 6, 12)


class FakeRequest:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeTasks:
    def __init__(self, store):
        self.store = store

    def list(self, **kw):
        return FakeRequest(lambda: {"items": [dict(t) for t in self.store.values()]})

    def insert(self, tasklist, body):
        def fn():
            task_id = f"t{len(self.store) + 1}"
            task = dict(body, id=task_id, status="needsAction")
            self.store[task_id] = task
            return task
        return FakeRequest(fn)

    def patch(self, tasklist, task, body):
        return FakeRequest(lambda: self.store[task].update(body) or self.store[task])

    def delete(self, tasklist, task):
        return FakeRequest(lambda: self.store.pop(task, None) and None)


class FakeService:
    """Just enough of the Tasks API: one fixed 'Revisions' list."""

    def __init__(self):
        self.store = {}  # task_id -> task dict

    def tasks(self):
        return FakeTasks(self.store)

    def tasklists(self):
        class Lists:
            def list(self, **kw):
                return FakeRequest(lambda: {"items": [{"id": "L1", "title": "Revisions"}]})
        return Lists()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def service():
    return FakeService()


@pytest.fixture
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(daemon.notify, "notify",
                        lambda title, msg: sent.append((title, msg)))
    return sent


def test_push_creates_tasks_for_due_items(conn, service, notifications):
    item_id = db.add_item(conn, "TCP/IP stack", date(2026, 6, 11),
                          [(0, "layers"), (1, "IP")])
    db.add_item(conn, "future thing", TODAY)  # due tomorrow, no task expected
    assert daemon.run_cycle(conn, service, TODAY)
    assert len(service.store) == 1
    task = next(iter(service.store.values()))
    assert task["title"] == "TCP/IP stack"
    assert task["notes"] == "☐ layers\n  ☐ IP"
    assert task["due"].startswith("2026-06-12")
    assert db.get_item(conn, item_id)["gtask_id"] == task["id"]


def test_checked_task_completes_revision_and_advances(conn, service, notifications):
    item_id = db.add_item(conn, "x", date(2026, 6, 10))  # due 6/11, overdue
    daemon.run_cycle(conn, service, TODAY)
    gid = db.get_item(conn, item_id)["gtask_id"]
    # user checks it off on the phone
    service.store[gid]["status"] = "completed"
    service.store[gid]["completed"] = "2026-06-12T19:30:00.000Z"
    daemon.run_cycle(conn, service, TODAY)
    item = db.get_item(conn, item_id)
    assert item["rung"] == 1
    assert item["next_due"] == "2026-06-15"  # completion + 3, not schedule + 3
    assert item["gtask_id"] is None
    assert gid not in service.store  # checked task removed from the list


def test_hand_deleted_task_is_recreated(conn, service, notifications):
    item_id = db.add_item(conn, "x", date(2026, 6, 10))
    daemon.run_cycle(conn, service, TODAY)
    old_gid = db.get_item(conn, item_id)["gtask_id"]
    del service.store[old_gid]  # deletion is not completion
    daemon.run_cycle(conn, service, TODAY)
    new_gid = db.get_item(conn, item_id)["gtask_id"]
    assert new_gid in service.store
    item = db.get_item(conn, item_id)
    assert item["rung"] == 0  # no revision was recorded


def test_orphan_tasks_are_removed(conn, service, notifications):
    service.store["stray"] = {"id": "stray", "title": "not ours",
                              "status": "needsAction"}
    daemon.run_cycle(conn, service, TODAY)
    assert "stray" not in service.store


def test_overdue_task_due_date_rolls_forward(conn, service, notifications):
    item_id = db.add_item(conn, "x", date(2026, 6, 9))  # due 6/10
    daemon.run_cycle(conn, service, date(2026, 6, 10))
    gid = db.get_item(conn, item_id)["gtask_id"]
    assert service.store[gid]["due"].startswith("2026-06-10")
    daemon.run_cycle(conn, service, TODAY)  # two days later, still unchecked
    assert service.store[gid]["due"].startswith("2026-06-12")


def test_digest_once_per_day_and_only_when_due(conn, service, notifications):
    daemon.run_cycle(conn, service, TODAY)
    assert notifications == []  # nothing due, no digest
    db.add_item(conn, "a", date(2026, 6, 10))
    db.add_item(conn, "b", date(2026, 6, 10))
    daemon.run_cycle(conn, service, TODAY)
    daemon.run_cycle(conn, service, TODAY)
    assert len(notifications) == 1
    assert "2 items due for revision: a, b" in notifications[0][1]
    daemon.run_cycle(conn, service, date(2026, 6, 13))
    assert len(notifications) == 2  # new day, new digest


def test_sync_failure_still_sends_digest(conn, notifications):
    db.add_item(conn, "a", date(2026, 6, 10))

    class Broken:
        def tasklists(self):
            raise ConnectionError("offline")

    assert daemon.run_cycle(conn, Broken(), TODAY) is False
    assert len(notifications) == 1
