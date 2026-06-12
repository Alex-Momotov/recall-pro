"""Serialize/parse item outlines (title + nested subpoints).

Text form (used by the edit window):

    Title line
    - top-level bullet
      - sub bullet
        - sub-sub bullet

Two spaces of indentation per depth level, "- " bullet marker.
"""
from __future__ import annotations

INDENT = "  "


def render_outline(title: str, subpoints: list[tuple[int, str]]) -> str:
    lines = [title]
    for depth, text in subpoints:
        lines.append(f"{INDENT * depth}- {text}")
    return "\n".join(lines)


def parse_outline(text: str) -> tuple[str, list[tuple[int, str]]]:
    """First non-empty line is the title; remaining lines are bullets.

    Bullet depth comes from leading indentation (2 spaces per level, tabs
    count as one level). Lines without a "- " marker are treated as bullets
    too, so hand-edited text degrades gracefully.
    """
    title = ""
    subpoints: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if not title:
            title = raw.strip()
            continue
        expanded = raw.replace("\t", INDENT)
        stripped = expanded.lstrip(" ")
        depth = (len(expanded) - len(stripped)) // len(INDENT)
        if stripped.startswith("- "):
            stripped = stripped[2:]
        elif stripped.startswith("-") and stripped != "-":
            stripped = stripped[1:].lstrip()
        text_part = stripped.strip()
        if text_part:
            subpoints.append((depth, text_part))
    return title, normalize_depths(subpoints)


def normalize_depths(subpoints: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Clamp depths so the outline is well-formed: first bullet at depth 0,
    each bullet at most one level deeper than its predecessor."""
    result: list[tuple[int, str]] = []
    prev_depth = -1
    for depth, text in subpoints:
        depth = max(0, min(depth, prev_depth + 1))
        result.append((depth, text))
        prev_depth = depth
    return result


def render_notes(subpoints: list[tuple[int, str]]) -> str:
    """Checklist rendering for the Google Task notes field."""
    return "\n".join(f"{INDENT * depth}☐ {text}" for depth, text in subpoints)
