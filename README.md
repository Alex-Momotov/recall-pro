# RecallPro

Personal spaced repetition without cards. You log *what* you learned (a title,
optionally with a checklist of subpoints) — never the content. RecallPro reminds
you when to revise it; the actual revision happens in your own notes.

## About / how it works

| Piece | Role |
|---|---|
| `recallpro` CLI (Python) | Capture and manage items; full-screen capture window (prompt_toolkit) |
| SQLite (`~/.recallpro/recallpro.db`) | Source of truth — items, subpoints, revision history |
| Daemon (`python -m recallpro.daemon`) | One sync cycle per run; launchd runs it at login + every 15 min |
| Google Tasks ("Revisions" list) | Display + completion surface, visible in Google Calendar on Mac & phone |
| macOS notification (osascript) | One digest per day: "N items due for revision: …" |

Flow: you capture an item → it's scheduled on the ladder **1, 3, 7, 14, 30,
60, 120 days, then doubling forever**. When due, the daemon creates a Google
Task. **Checking off the task is the only way to complete a revision** — the
daemon picks that up, advances the ladder, and counts the next interval from
the *completion* date. Unchecked tasks roll forward to today, every day, until
done. If the Mac sleeps, everything catches up on the next wake.

## Requirements

- macOS (the daemon uses `launchd` and `osascript`)
- Python 3.10+
- A Google account (for Google Tasks / Calendar integration)

## Install

```sh
git clone https://github.com/<your-username>/recall-pro.git
cd recall-pro
python3 -m venv .venv
.venv/bin/pip install -e .
```

### Put `recallpro` on your PATH

```sh
ln -s "$PWD/.venv/bin/recallpro" ~/.local/bin/recallpro   # or any dir already on PATH
```

If you later move or rename the project directory, recreate the venv and
symlink and re-run `recallpro setup` — they all embed absolute paths.

### Connect Google + install the daemon

```sh
recallpro setup
```

The first run prints the one-time Google Cloud steps: create a project,
enable the **Google Tasks API**, create a **Desktop app** OAuth client, save
the downloaded JSON as `~/.recallpro/credentials.json`, and **publish the
OAuth app** (otherwise Google expires the refresh token every 7 days). Then
re-run `recallpro setup` — it opens the browser consent flow, creates the
"Revisions" task list, and installs + loads the launchd agent. Idempotent;
re-run it anytime something looks broken.

## Daemon management (launchd)

The agent lives at `~/Library/LaunchAgents/com.recallpro.agent.plist`.

```sh
# add (done automatically by `recallpro setup`)
launchctl load ~/Library/LaunchAgents/com.recallpro.agent.plist

# remove from the daemon list
launchctl unload ~/Library/LaunchAgents/com.recallpro.agent.plist

# is it registered / healthy?  (shows PID and last exit code; 0 = ok)
launchctl list | grep com.recallpro.agent

# app-level health: last sync, last digest, auth, counts
recallpro status

# logs
tail -f ~/.recallpro/daemon.log
```

## Uninstall

```sh
launchctl unload ~/Library/LaunchAgents/com.recallpro.agent.plist
rm ~/Library/LaunchAgents/com.recallpro.agent.plist
rm -rf ~/.recallpro          # deletes all items + auth — back up first if unsure
rm ~/.local/bin/recallpro    # the PATH symlink, if you made one
rm -rf .venv                 # or delete the whole project directory
```

## Cheat sheet

```text
recallpro                      capture window (multiple items per session)
recallpro TCP/IP stack         one-shot capture, no quotes needed
recallpro <title> --on DATE    backdate: YYYY-MM-DD, 'yesterday', 'today'
recallpro due [--full]         what's due today (--full shows subpoints)
recallpro ls                   all items with rung and next due date
recallpro edit <id|text>       edit title/subpoints in the editor
recallpro delete <id…|text>    remove item(s), no confirmation — e.g. delete 3 5 7
recallpro sync                 force a sync cycle right now
recallpro status               daemon / sync / auth health
recallpro help                 usage
```

Capture window:

```text
First line = title; lines below = subpoints, written as "- text"
(indent 2 spaces per level; Tab inserts one level)

Enter on an empty line    save item, start the next one
Esc / Ctrl-C / Ctrl-D     exit (in-progress item is saved)
```

Completing a revision = **check the task off in Google Tasks / Calendar**
(Mac, phone, or web). There is no CLI completion command.
