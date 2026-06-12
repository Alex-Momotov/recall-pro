"""`recallpro setup` — idempotent one-time bootstrap:
Google OAuth consent, "Revisions" task list, launchd agent install."""
from __future__ import annotations

import subprocess
import sys

from . import config, db, gtasks

CREDENTIALS_HELP = f"""\
Google OAuth client credentials not found at:
    {config.CREDENTIALS_PATH}

One-time Google Cloud setup:
  1. https://console.cloud.google.com → create (or pick) a project
  2. APIs & Services → Library → enable "Google Tasks API"
  3. APIs & Services → Credentials → Create credentials →
     OAuth client ID → Application type: Desktop app
  4. Download the JSON and save it as {config.CREDENTIALS_PATH}
  5. OAuth consent screen → Audience → "Publish app" (otherwise the
     refresh token expires every 7 days and you'd re-consent weekly)

Then run `recallpro setup` again.
"""

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>recallpro.daemon</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""


def run() -> int:
    config.migrate_legacy_data()
    config.RECALLPRO_DIR.mkdir(parents=True, exist_ok=True)

    if not config.CREDENTIALS_PATH.exists():
        print(CREDENTIALS_HELP, end="")
        return 1

    creds = gtasks.load_credentials()
    if creds is None:
        print("Opening browser for Google consent…")
        gtasks.run_oauth_flow()
    print("✓ Google authentication OK")

    service = gtasks.get_service()
    list_id = gtasks.ensure_list(service)
    conn = db.connect()
    db.meta_set(conn, "gtasks_list_id", list_id)
    print(f'✓ Google Tasks list "{config.GTASKS_LIST_TITLE}" ready')

    install_launchd()
    print("✓ setup complete — daemon runs at login and every "
          f"{config.DAEMON_INTERVAL_SECONDS // 60} minutes while awake")
    return 0


def install_launchd() -> None:
    # Retire any pre-rename agents that may still be loaded.
    for legacy in config.LEGACY_PLIST_PATHS:
        if legacy.exists():
            subprocess.run(["launchctl", "unload", str(legacy)],
                           capture_output=True)
            legacy.unlink()
            print(f"✓ removed old launchd agent ({legacy.name})")
    plist = PLIST_TEMPLATE.format(
        label=config.PLIST_LABEL,
        python=sys.executable,
        interval=config.DAEMON_INTERVAL_SECONDS,
        log=config.LOG_PATH,
    )
    config.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "unload", str(config.PLIST_PATH)],
                   capture_output=True)
    result = subprocess.run(["launchctl", "load", str(config.PLIST_PATH)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"warning: launchctl load failed: {result.stderr.strip()}",
              file=sys.stderr)
    else:
        print(f"✓ launchd agent installed ({config.PLIST_PATH})")
