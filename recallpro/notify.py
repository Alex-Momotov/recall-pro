"""macOS notifications via osascript. Best-effort: never raises."""
import subprocess


def notify(title: str, message: str) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=10)
    except Exception:
        pass
