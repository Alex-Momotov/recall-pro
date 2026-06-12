"""Full-screen terminal UIs (prompt_toolkit).

Capture window (bare `recallpro`) and edit window (`recallpro edit`) share the same
editing model: free multi-line text where the first line is the title and
subsequent lines are subpoints written by hand as "- text", indented two
spaces (or Tab) per level.

Capture: pressing Enter on an empty line (a blank line after the item)
finalizes it — committed to SQLite immediately, "✓ added" shown above, editor
cleared for the next item. Exit keys also save an in-progress item, so no
path can lose typed text.
"""
from __future__ import annotations

from datetime import date

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from . import db, outline

STYLE = Style.from_dict({
    "hint": "fg:ansibrightblack",
    "saved": "fg:ansigreen",
    "warn": "fg:ansiyellow",
})

CAPTURE_HINT = ("RecallPro capture — first line: title · '- ' lines: subpoints · "
                "Enter on empty line: save item · Esc: exit")
EDIT_HINT = ("RecallPro edit — first line is the title, '- ' lines are "
             "subpoints · Esc: save · Ctrl-C: cancel")


def run_capture(conn=None, input=None, output=None) -> int:
    """input/output are injectable for tests (pipe input + DummyOutput)."""
    if conn is None:
        conn = db.connect()
    saved_log: list[tuple[str, str]] = []
    saved = 0
    area = TextArea(multiline=True, wrap_lines=False)

    def save_block() -> None:
        nonlocal saved
        title, subpoints = outline.parse_outline(area.text)
        if not title:
            area.text = ""
            return
        dupes = db.find_by_title_exact(conn, title)
        item_id = db.add_item(conn, title, date.today(), subpoints)
        n = len(subpoints)
        detail = f" ({n} subpoint{'s' if n != 1 else ''})" if n else ""
        saved_log.append(("class:saved", f"✓ added #{item_id}  {title}{detail}\n"))
        if dupes:
            saved_log.append(
                ("class:warn", f"  duplicate of #{dupes[0]['id']} (same title)\n"))
        saved += 1
        area.text = ""

    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        buf = area.buffer
        if buf.document.current_line.strip() == "" and buf.text.strip():
            save_block()
        elif buf.text.strip():
            buf.insert_text("\n")
        # Enter on an entirely empty editor: nothing to do

    @kb.add("tab")
    def _(event):
        area.buffer.insert_text(outline.INDENT)

    def do_exit(event):
        save_block()
        event.app.exit(result=None)

    kb.add("escape", eager=True)(do_exit)
    kb.add("c-c")(do_exit)
    kb.add("c-d")(do_exit)

    layout = Layout(HSplit([
        Window(FormattedTextControl([("class:hint", CAPTURE_HINT)]), height=1),
        Window(FormattedTextControl(lambda: saved_log), dont_extend_height=True),
        area,
    ]))
    app = Application(layout=layout, key_bindings=kb, full_screen=True,
                      style=STYLE, input=input, output=output)
    app.layout.focus(area)
    app.run()
    print(f"Saved {saved} item{'s' if saved != 1 else ''}.")
    return 0


def run_edit(conn, item_id: int, input=None, output=None) -> int:
    item = db.get_item(conn, item_id)
    text = outline.render_outline(item["title"], db.get_subpoints(conn, item_id))
    area = TextArea(text=text, multiline=True, scrollbar=True, wrap_lines=False)
    area.buffer.cursor_position = len(area.text)

    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def _(event):
        event.app.exit(result=area.text)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    @kb.add("tab")
    def _(event):
        area.buffer.insert_text(outline.INDENT)

    layout = Layout(HSplit([
        Window(FormattedTextControl([("class:hint", EDIT_HINT)]), height=1),
        area,
    ]))
    app = Application(layout=layout, key_bindings=kb, full_screen=True,
                      style=STYLE, input=input, output=output)
    app.layout.focus(area)
    result = app.run()
    if result is None:
        print("edit cancelled")
        return 1
    title, subpoints = outline.parse_outline(result)
    if not title:
        print("error: empty title — not saved")
        return 1
    db.update_title(conn, item_id, title)
    db.set_subpoints(conn, item_id, subpoints)
    print(f'✓ updated #{item_id} "{title}" ({len(subpoints)} subpoints)')
    sync_item_task(conn, item_id)
    return 0


def sync_item_task(conn, item_id: int) -> None:
    """Opportunistic: push the new title/notes to the item's Google Task.
    Never fails — the daemon reconciles on its next cycle anyway."""
    try:
        item = db.get_item(conn, item_id)
        if not item or not item["gtask_id"]:
            return
        from . import gtasks
        service = gtasks.get_service()
        list_id = gtasks.ensure_list(service)
        gtasks.patch_task(service, list_id, item["gtask_id"], {
            "title": item["title"],
            "notes": outline.render_notes(db.get_subpoints(conn, item_id)),
        })
    except Exception:
        pass
