"""One sync cycle, run by launchd every 15 minutes and at load.

Order matters: completions are reconciled first (so a just-completed item
doesn't get its task recreated), then due items are pushed, then the daily
digest fires. The digest uses only local state, so it works even when Google
is unreachable.
"""
from __future__ import annotations

import sys
from datetime import date, datetime

from . import db, outline, notify

DIGEST_TITLES_SHOWN = 3


def run_cycle(conn, service=None, today: date | None = None) -> bool:
    today = today or date.today()
    sync_error: Exception | None = None
    if service is None:
        try:
            from . import gtasks
            service = gtasks.get_service()
        except Exception as e:
            sync_error = e
            service = None
    if service is not None:
        try:
            sync(conn, service, today)
            db.meta_set(conn, "last_sync",
                        datetime.now().isoformat(timespec="seconds"))
        except Exception as e:
            sync_error = e
    send_digest(conn, today)
    if sync_error is not None:
        print(f"recallpro daemon: sync skipped ({sync_error})", file=sys.stderr)
    return sync_error is None


def sync(conn, service, today: date) -> None:
    from . import gtasks
    list_id = gtasks.ensure_list(service)
    tasks = gtasks.fetch_tasks(service, list_id)
    reconcile_completions(conn, service, list_id, tasks)
    push_due(conn, service, list_id, tasks, today)


def reconcile_completions(conn, service, list_id: str, tasks: list[dict]) -> None:
    from . import gtasks
    by_id = {t["id"]: t for t in tasks}
    referenced: set[str] = set()
    for item in db.list_items(conn):
        gid = item["gtask_id"]
        if not gid:
            continue
        referenced.add(gid)
        task = by_id.get(gid)
        if task is not None and task.get("status") == "completed":
            db.complete_revision(conn, item, completed_date(task))
            gtasks.delete_task(service, list_id, gid)
    # The daemon owns the list: anything it didn't create gets removed.
    for task in tasks:
        if task["id"] not in referenced:
            gtasks.delete_task(service, list_id, task["id"])


def completed_date(task: dict) -> date:
    stamp = task.get("completed")
    if not stamp:
        return date.today()
    try:
        return (datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                .astimezone().date())
    except ValueError:
        return date.today()


def push_due(conn, service, list_id: str, tasks: list[dict], today: date) -> None:
    from . import gtasks
    by_id = {t["id"]: t for t in tasks}
    for item in db.due_items(conn, today):
        notes = outline.render_notes(db.get_subpoints(conn, item["id"]))
        gid = item["gtask_id"]
        task = by_id.get(gid) if gid else None
        if task is None or task.get("status") == "completed":
            # No task yet, or it was deleted by hand (deletion ≠ completion):
            # (re)create. Completed tasks were already handled in reconcile.
            if task is None:
                new_id = gtasks.insert_task(
                    service, list_id, item["title"], notes, today)
                db.set_gtask_id(conn, item["id"], new_id)
            continue
        stale = (task.get("title") != item["title"]
                 or (task.get("notes") or "") != notes
                 or not (task.get("due") or "").startswith(today.isoformat()))
        if stale:
            gtasks.patch_task(service, list_id, gid, {
                "title": item["title"],
                "notes": notes,
                "due": gtasks.due_rfc3339(today),
            })


def send_digest(conn, today: date) -> None:
    due = db.due_items(conn, today)
    if not due:
        return
    if db.meta_get(conn, "last_digest_date") == today.isoformat():
        return
    titles = [i["title"] for i in due]
    shown = ", ".join(titles[:DIGEST_TITLES_SHOWN])
    if len(titles) > DIGEST_TITLES_SHOWN:
        shown += ", …"
    plural = "s" if len(due) != 1 else ""
    notify.notify("RecallPro", f"{len(due)} item{plural} due for revision: {shown}")
    db.meta_set(conn, "last_digest_date", today.isoformat())


def main() -> int:
    conn = db.connect()
    run_cycle(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
