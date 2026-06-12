"""CLI entry point. Capture is the default action: anything that isn't a
reserved subcommand is treated as a new item title (args joined, no quotes
needed). Bare `recallpro` opens the full-screen capture window."""
from __future__ import annotations

import difflib
import sqlite3
import sys
from datetime import date, timedelta

from . import db, scheduler

RESERVED = {"ls", "edit", "del", "setup", "status", "sync", "help"}

USAGE = """\
recallpro — personal spaced repetition reminder

  recallpro                     open the capture window (title + subpoints)
  recallpro <title words>       one-shot capture, learned today
  recallpro <title> --on DATE   backdate (YYYY-MM-DD, 'yesterday', or 'today')

  recallpro ls [--due] [--full] all items (--due: only due today; --full: subpoints)
  recallpro edit <id|text>      edit an item's title/subpoints in the editor
  recallpro del <id…|text>      permanently delete item(s) — several ids allowed
  recallpro setup               Google OAuth + task list + launchd install
  recallpro status              daemon and sync health
  recallpro sync                run a full sync cycle right now
  recallpro help                this message

Completion happens only by checking off the task in Google Tasks / Calendar.
Titles starting with a reserved word: use the capture window (bare `recallpro`).
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from . import tui
        return tui.run_capture()
    cmd = argv[0]
    if cmd in ("help", "-h", "--help"):
        print(USAGE, end="")
        return 0
    if cmd == "ls":
        return cmd_list(argv[1:])
    if cmd == "edit":
        return cmd_edit(argv[1:])
    if cmd == "del":
        return cmd_delete(argv[1:])
    if cmd == "setup":
        from . import setup_cmd
        return setup_cmd.run()
    if cmd == "status":
        return cmd_status()
    if cmd == "sync":
        return cmd_sync()
    return cmd_capture(argv)


# --- capture ---------------------------------------------------------------

def parse_capture_args(args: list[str], today: date | None = None
                       ) -> tuple[str, date]:
    """Split out --on and join the rest into the title."""
    today = today or date.today()
    words: list[str] = []
    learned_on = today
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--on":
            if i + 1 >= len(args):
                raise ValueError("--on requires a date (YYYY-MM-DD or 'yesterday')")
            learned_on = parse_date(args[i + 1], today)
            i += 2
        elif arg.startswith("--on="):
            learned_on = parse_date(arg.split("=", 1)[1], today)
            i += 1
        else:
            words.append(arg)
            i += 1
    title = " ".join(words).strip()
    if not title:
        raise ValueError("empty title")
    if learned_on > today:
        raise ValueError(f"--on date {learned_on} is in the future")
    return title, learned_on


def parse_date(text: str, today: date) -> date:
    text = text.strip().lower()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"can't parse date {text!r} (use YYYY-MM-DD or 'yesterday')")


def cmd_capture(args: list[str]) -> int:
    try:
        title, learned_on = parse_capture_args(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    conn = db.connect()
    dupes = db.find_by_title_exact(conn, title)
    item_id = db.add_item(conn, title, learned_on)
    item = db.get_item(conn, item_id)
    due = max(date.fromisoformat(item["next_due"]), date.today())
    print(f'✓ #{item_id} "{title}" — first revision {format_day(due)}')
    for d in dupes:
        print(f'  note: duplicate of #{d["id"]} (same title)')
    return 0


# --- review ----------------------------------------------------------------

def cmd_list(args: list[str]) -> int:
    due_only = "--due" in args
    full = "--full" in args
    conn = db.connect()
    today = date.today()
    rows = db.due_items(conn, today) if due_only else db.list_items(conn)
    if not rows:
        print("Nothing due today." if due_only else
              "No items yet. Run `recallpro` or `recallpro <title>` to capture one.")
        return 0
    for item in rows:
        nd = date.fromisoformat(item["next_due"])
        if due_only:
            overdue = scheduler.overdue_days(nd, today)
            tag = f"{overdue}d overdue" if overdue else "due today"
        else:
            when = format_day(max(nd, today)) if nd <= today else nd.isoformat()
            tag = f"next {when:<12}"
        print(f'#{item["id"]:<4} r{item["rung"]:<3} {tag:<12} {item["title"]}')
        if full:
            for depth, text in db.get_subpoints(conn, item["id"]):
                print(f'{" " * 25}{"  " * depth}- {text}')
    return 0


def format_day(d: date) -> str:
    today = date.today()
    if d <= today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return d.isoformat()


# --- lifecycle ---------------------------------------------------------------

def resolve_item(conn, ref_args: list[str]) -> sqlite3.Row | None:
    """Resolve an item by numeric id or case-insensitive title substring.
    Ambiguity → numbered picker on stdin. Returns None if not resolved."""
    ref = " ".join(ref_args).strip()
    if not ref:
        print("error: give an item id or part of its title", file=sys.stderr)
        return None
    if ref.isdigit():
        item = db.get_item(conn, int(ref))
        if not item:
            print(f"error: no item #{ref}", file=sys.stderr)
        return item
    matches = db.find_by_title_substring(conn, ref)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        titles = [r["title"] for r in db.list_items(conn)]
        close = difflib.get_close_matches(ref, titles, n=3, cutoff=0.4)
        print(f"error: no item matching {ref!r}", file=sys.stderr)
        if close:
            print("did you mean: " + "; ".join(close), file=sys.stderr)
        return None
    print(f"{len(matches)} items match {ref!r}:")
    for n, item in enumerate(matches, 1):
        print(f"  {n}. #{item['id']} {item['title']}")
    try:
        choice = input("which one? [number, empty to cancel] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(matches):
        return matches[int(choice) - 1]
    return None


def cmd_edit(args: list[str]) -> int:
    conn = db.connect()
    item = resolve_item(conn, args)
    if not item:
        return 1
    from . import tui
    return tui.run_edit(conn, item["id"])


def cmd_delete(args: list[str]) -> int:
    conn = db.connect()
    rc = 0
    if args and all(a.isdigit() for a in args):
        items = []
        for a in args:
            item = db.get_item(conn, int(a))
            if item is None:
                print(f"error: no item #{a}", file=sys.stderr)
                rc = 1
            else:
                items.append(item)
    else:
        item = resolve_item(conn, args)
        if not item:
            return 1
        items = [item]
    gtask_ids = [i["gtask_id"] for i in items if i["gtask_id"]]
    for item in items:
        db.delete_item(conn, item["id"])
        print(f'✓ deleted "{item["title"]}"')
    if gtask_ids:
        try:
            from . import gtasks
            service = gtasks.get_service()
            list_id = gtasks.ensure_list(service)
            for gid in gtask_ids:
                gtasks.delete_task(service, list_id, gid)
        except Exception:
            pass  # daemon's orphan cleanup removes the tasks on its next cycle
    return rc


# --- sync --------------------------------------------------------------------

def cmd_sync() -> int:
    from . import daemon
    conn = db.connect()
    if daemon.run_cycle(conn):
        print(f"✓ synced ({db.meta_get(conn, 'last_sync')})")
        return 0
    print("sync failed — run `recallpro setup` if Google isn't connected yet",
          file=sys.stderr)
    return 1


# --- status ------------------------------------------------------------------

def cmd_status() -> int:
    import json

    from . import config
    conn = db.connect()
    today = date.today()
    active = len(db.list_items(conn))
    due = len(db.due_items(conn, today))
    print(f"db:          {config.DB_PATH}")
    print(f"items:       {active} active, {due} due today")
    print(f"last sync:   {db.meta_get(conn, 'last_sync') or 'never'}")
    print(f"last digest: {db.meta_get(conn, 'last_digest_date') or 'never'}")
    if config.TOKEN_PATH.exists():
        try:
            expiry = json.loads(config.TOKEN_PATH.read_text()).get("expiry")
            print(f"google auth: token present (access token expiry {expiry})")
        except (ValueError, OSError):
            print("google auth: token file unreadable — re-run `recallpro setup`")
    else:
        print("google auth: not set up — run `recallpro setup`")
    loaded = config.PLIST_PATH.exists()
    print(f"launchd:     {'installed' if loaded else 'not installed'} ({config.PLIST_PATH})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
