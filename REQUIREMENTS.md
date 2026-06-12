# RecallPro — Personal Spaced Repetition Reminder

## Concept

A title-only spaced repetition tool. Unlike Anki, no card content is ever stored —
you log *what* you learned (a syllabus-style title), and the system reminds you
*when* to revise it. The actual revision happens in your own notes, outside this tool.

Each item carries exactly two pieces of information at capture time:

1. **What** you learned (free-text title)
2. **When** you learned it (defaults to today; backdatable)

## Core Scheduling Rules

- **Interval ladder:** 1, 3, 7, 14, 30, 60, 120 days — then keeps doubling
  forever (240, 480, 960, …). Items never retire on their own.
- **Intervals count from the last successful revision**, not from when the
  revision was scheduled. If a revision was due Jan 1 but completed Jan 3,
  the next interval starts from Jan 3.
- **Overdue items roll forward.** A revision that isn't marked complete stays
  due "today", every day, until it is completed. Items can never be silently
  skipped.
- Completing a revision always advances the item one rung up the ladder
  (no penalty for completing late, no recall rating).

## Architecture

```
┌────────────────┐  learned "X"  ┌──────────────────────────┐
│ CLI (recallpro)├──────────────▶│  SQLite (source of truth)│
└────────────────┘               └────────────┬─────────────┘
       ▲                                      │
       │ due / ls / edit                      │ read/write
       │                         ┌────────────▼─────────────┐
       └─────────────────────────┤  Daemon (launchd agent)  │
                                 │  - compute due items     │
                                 │  - sync Google Tasks ◀──▶│── Google Tasks API
                                 │  - macOS daily digest    │   ("Revisions" list,
                                 └──────────────────────────┘    visible in Google
                                                                 Calendar on Mac+phone)
```

- **Language:** Python. **Storage:** SQLite, single local DB file. The local DB
  is the source of truth; Google Tasks is a synced view.
- **Daemon:** runs locally on the MacBook as a `launchd` user agent (periodic
  interval + run-at-load, so it fires on login/wake). Explicitly accepted
  trade-off: if the Mac is asleep/off, nothing happens. On the next run it
  catches up fully — syncs tasks, rolls overdue items to today, sends the digest.
- **No cloud component.** Google Tasks/Calendar is used only as a display +
  completion surface.

## Components

### 1. CLI (`recallpro`)

**Guiding principle:** minimum keystrokes. Capture is the default action; item
lookups never require exact titles or quotes.

**Item referencing convention (applies to `edit` and `delete`):** an item
argument is either a numeric id or a
case-insensitive substring of the title. Unique match → act immediately.
Ambiguous match → numbered list, pick by number. No match → error listing
nearest titles.

#### Items have subpoints

An item is a **title plus an optional outline of subpoints** (arbitrarily
nested bullets) — a syllabus breakdown acting as a revision checklist, *not*
card content. Subpoints are display-only: they appear in `recallpro due`
(`--full`), in the capture/edit window, and rendered as an indented checklist
in the Google Task's **notes field** (the Tasks API supports only one level of
subtasks, so notes-field rendering is used instead of real subtasks).
Completion remains a single checkbox per item.

#### Capture

| Command | Behavior |
|---|---|
| `recallpro` | Opens the **full-screen capture window** (see below). |
| `recallpro TCP/IP stack` | One-shot capture; all args joined into the title — no quotes needed. Title only (no subpoints in one-shot mode). Learned today; first revision due tomorrow. |
| `recallpro <title> --on 2026-06-10` / `--on yesterday` | Backdated capture; schedule computed from that date. If the computed first due date is already past → due today. |

Titles starting with a reserved word (`due, ls, edit, delete, setup,
status, sync, help`) can't be captured one-shot — use the capture window,
where every line is plain text.

**Capture window (bare `recallpro`)** — full-screen editor (prompt_toolkit),
same free-text editing model as the edit window:

- The first line of the current block is the **title**; subsequent lines are
  subpoints written by hand as `- text`, indented two spaces per level
  (Tab inserts one level; literal tabs also count as one level).
- **Enter on an empty line** (a blank line after the item, i.e. double Enter)
  finalizes the item: committed to SQLite immediately, "✓ added" shown in the
  log directly above, editor clears for the next item. A title-only item is
  still just two Enters.
- Normal cursor movement and editing work anywhere within the current block
  until it is finalized.
- Esc / Ctrl-C / Ctrl-D exits; an in-progress block with a non-empty title is
  saved on exit, so no exit path can lose typed text.
- Any characters are valid (quotes, apostrophes, slashes) — the shell never
  parses this text. Duplicate titles are added anyway with a visible
  "duplicate of #N" warning (fix with `recallpro delete` or `recallpro edit`).

#### Review

| Command | Behavior |
|---|---|
| `recallpro due` | Items due today, incl. rolled-over ones (shown with "3d overdue"), with id and rung. `--full` includes each item's subpoint outline. |
| `recallpro ls` | All active items: id, title, rung, next due date. |

#### Completion

**Checking off the Google Task is the only completion mechanism** — from the
Google Tasks / Calendar app on Mac, phone, or web. The daemon detects the
checked task on its next cycle, records the revision, advances the rung, and
schedules the next one. There is no CLI completion command. Consequences:

- Early revision isn't possible: a task only exists once the item is due.
- Completion takes effect (rung advance, next task) only after the daemon's
  next sync — checking the box on your phone while the Mac sleeps is fine;
  it's picked up when the Mac wakes.

#### Lifecycle

| Command | Behavior |
|---|---|
| `recallpro edit <item>` | Reopens the item (title + subpoints) in the outline editor — covers both renaming and revising the breakdown. Synced Google Task updates on next sync. |
| `recallpro delete <item>` | Hard delete, no confirmation — the only way to stop an item (no archive). History removed; its Google Task is removed. Accepts several space-separated ids (`delete 3 5 7`); if every arg is numeric they're treated as ids, otherwise the args are one title substring. |

#### System

| Command | Behavior |
|---|---|
| `recallpro setup` | One-time bootstrap: Google OAuth consent flow, create the "Revisions" task list, install + load the launchd agent. Idempotent — safe to re-run to repair. |
| `recallpro status` | Daemon health: last sync time, last digest date, OAuth token validity, active/due counts. |
| `recallpro sync` | Force a full sync cycle immediately (don't wait for the next 15-min tick). |
| `recallpro help` | Usage summary. |

CLI writes to SQLite directly — capture must succeed even if the daemon is down
or the Mac is offline; the daemon reconciles Google Tasks on its next cycle
(every ~15 min). Commands with sync-visible effects (`edit`, `delete`) trigger
an opportunistic immediate sync but never fail if it's unavailable.

### 2. Daemon (sync + notify loop)

On each cycle (every ~15 min while awake, and immediately on start):

1. **Compute due set:** every active item whose `next_due <= today`.
2. **Google Tasks sync (two-way):**
   - Ensure a task exists in the dedicated **"Revisions"** task list for each
     due item, dated today. **Known API limitation:** the Tasks API discards
     the time portion of `due` (date-only), so the intended 9 PM due time
     cannot be set programmatically — phone notification behavior for
     date-only tasks must be verified on day one; ntfy.sh is the fallback if
     it proves unreliable. The item's subpoint outline is rendered as an
     indented checklist in the task's notes field. Overdue tasks get their due
     date moved to today (roll-forward).
   - Detect tasks the user checked off in Google Tasks (Mac or phone) →
     record the revision as completed in SQLite at the task's completion
     time, advance the ladder, delete/close the task.
   - The daemon owns the "Revisions" list outright and may freely create,
     update, and remove tasks in it. It never touches other lists.
3. **macOS digest notification:** at most one per calendar day (and on the
   first cycle after waking into a new day): *"3 items due for revision: A, B, C"*.
   No per-item notifications.

**Phone notifications** come from the Google Tasks/Calendar app's own due-date
reminders — no extra push service. Known limitation (accepted): if the Mac never
woke to sync a task, the phone won't know about it.

### 3. Storage (SQLite)

```
items:      id, title, learned_on, rung, next_due, gtask_id (nullable), created_at
subpoints:  id, item_id, position, depth, text   -- ordered outline, depth 0 = top bullet
revisions:  id, item_id, due_on, completed_on
meta:       last_digest_date, sync cursors, etc.
```

Ladder is computed, not stored: `interval(rung) = [1,3,7,14,30,60,120][rung]`
for rung ≤ 6, else `120 * 2^(rung-6)`.

## Edge Cases & Conflict Rules

- **Task deleted by hand in Google Tasks** (not checked off) → daemon recreates it
  next cycle; deletion is not completion. Use `recallpro delete` to stop an item.
- **Duplicate titles** → allowed, but the CLI warns; `edit`/`delete` on an
  ambiguous title shows a numbered picker.
- **Completion seen twice** (e.g. task checked, daemon crashes mid-cycle,
  reprocessed next cycle) → idempotent: a revision per item per due date counts
  once.
- **Backdated capture** where computed first revision is already in the past →
  due today (roll-forward applies from the start).
- **Multi-day absence** → no per-day back-fill: each overdue item appears once,
  due today. One digest, one task per item.
- **Clock semantics:** all scheduling at day granularity in local time; the
  9:00 PM task due time is purely a notification trigger, not a deadline —
  an item is "due" for the whole day.

## Decisions Log (2026-06-12)

- Schedule: fixed ladder, no recall ratings (SM-2 rejected as added friction).
- Ladder: 1-3-7-14-30-60-120 then doubling forever; no auto-retirement.
- Completion: **Google Tasks checkbox only** — no CLI completion command.
  Consequence: early revision isn't possible (a task exists only once due).
- Phone notifications: native Google Tasks/Calendar reminders only.
- Mac notifications: single daily digest.
- Input: CLI only (inbox file / Siri Shortcut / Telegram considered, deferred).
- Tasks live in a dedicated, daemon-owned "Revisions" list.
- Daemon: local launchd agent; cloud explicitly rejected.
- Tasks were meant to get a 9:00 PM due time for phone push notifications, but
  the Tasks API stores due dates date-only — notification reliability must be
  tested; ntfy.sh is the agreed fallback channel if Google's app doesn't push.
- Bare `recallpro` opens a full-screen capture window; every save commits
  immediately. Originally a modal bullet-by-bullet flow; changed same day to
  the edit window's free-text model (manual `- ` hyphens, blank line / double
  Enter finalizes the item) for simplicity and to avoid dead screen space.
- Items have nested subpoints (revision checklist, not card content), rendered
  into the Google Task notes field; completion stays one checkbox per item.
- Command set kept minimal: `due, ls, edit, delete, setup, status, sync,
  help` + default capture (`list` renamed to `ls`). Removed: `done, undo, archive, restore, rename,
  log, add`. `edit` (outline editor) covers renaming; `delete` is the only
  way to stop an item. (`sync` was removed, then re-added same day.)

## Setup Prerequisites (one-time)

- Google Cloud project with the **Google Tasks API** enabled, OAuth desktop-app
  credentials, one interactive consent flow; daemon stores the refresh token locally.
- `launchd` plist installed under `~/Library/LaunchAgents/`.

## Out of Scope (for now)

- Card content of any kind.
- Capture from phone (inbox file / Shortcut / bot) — possible later additions.
- Cloud/server deployment.
- Recall-quality ratings or adaptive intervals.
