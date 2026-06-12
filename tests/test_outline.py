from recallpro import outline


def test_render_parse_roundtrip():
    title = "Threads in Java"
    subs = [(0, "Thread class"), (1, "run vs start"), (2, "common mistake"),
            (0, "Executors")]
    text = outline.render_outline(title, subs)
    assert outline.parse_outline(text) == (title, subs)


def test_parse_handles_quotes_and_blank_lines():
    text = 'What\'s a "mutex"?\n\n- it locks\n'
    title, subs = outline.parse_outline(text)
    assert title == 'What\'s a "mutex"?'
    assert subs == [(0, "it locks")]


def test_parse_tabs_and_missing_dash():
    text = "T\n- a\n\tb\n"
    assert outline.parse_outline(text) == ("T", [(0, "a"), (1, "b")])


def test_normalize_depths_clamps_jumps():
    # first bullet forced to 0; jumps deeper than +1 clamped
    assert outline.normalize_depths([(2, "a"), (5, "b"), (0, "c")]) == [
        (0, "a"), (1, "b"), (0, "c")]


def test_render_notes_checklist():
    assert outline.render_notes([(0, "a"), (1, "b")]) == "☐ a\n  ☐ b"
