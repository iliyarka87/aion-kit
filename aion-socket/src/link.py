"""Local link between a director agent and an executor agent.

Both agents run on the same machine, as the same user, on the same disk.
This module opens a door between them. No network is involved at any step.

How a message reaches the executor:

    1. read the live window passport:  ~/.claude/sessions/<pid>.json
       it holds the session id and the process id; a sibling .key file
       keeps strangers out
    2. knock on an AF_UNIX socket at the address from that passport
    3. the text shows up in the executor's window as an ordinary message

AF_UNIX is not a network socket. It has no internet address, no port and no
way out of this machine. Unplug the network and the link keeps working.

The answer travels back the same way: the executor replies in its own window,
and this module reads that window's transcript **from a mark taken before the
message was sent**, so old words are never mistaken for new ones.

Usage:

    python3 link.py windows                list live executor windows
    python3 link.py send "text"            put a message in the window
    python3 link.py read <mark> [session]  read what was said after the mark
    python3 link.py round "text"           send, wait for the reply, print it
"""
import sys
import time
from pathlib import Path

# Local helpers that own the socket details. None of them touch the network.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mailbox"))   # модули почтового ящика окна
import iz_sessii as transcript   # noqa: E402  read a window's transcript
import sessii as windows         # noqa: E402  which windows are alive
import v_sessiyu as mailbox      # noqa: E402  put a message in a window

CHOSEN_WINDOW = Path("/private/tmp/claude-502/голос-мост/vybor-sessii.txt")
REPLY_TIMEOUT = 900   # seconds to wait for the executor to finish
POLL = 5              # seconds between checks
SETTLED_MIN = 40      # a reply shorter than this is not treated as final


def target_window() -> str:
    """Where to deliver: the owner's choice, else the freshest live window."""
    try:
        chosen = CHOSEN_WINDOW.read_text(encoding="utf-8").strip()
        if len(chosen) >= 8:
            return chosen
    except Exception:
        pass
    alive = windows.живые()
    return alive[0]["id"] if alive else ""


def mark(session: str) -> int:
    """Current end of the window's transcript. Taken before sending."""
    path = transcript.журнал(session)
    try:
        return path.stat().st_size if path else 0
    except Exception:
        return 0


def said_after(session: str, since: int) -> str:
    """Executor speech that appeared after the mark. Old text is ignored."""
    path = transcript.журнал(session)
    if not path:
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(since)
        parts = [transcript._речь(line) for line in handle]
    return "\n".join(p for p in parts if p).strip()


def send(text: str) -> tuple:
    """(delivered, session, mark_or_reason)."""
    session = target_window()
    if not session:
        return False, "", "no live executor window"
    before = mark(session)
    if not mailbox.послать(session, text):
        return False, session, "window refused the message"
    return True, session, str(before)


def wait_for_reply(session: str, since: int, timeout: int = REPLY_TIMEOUT) -> str:
    """Wait until the reply stops growing, then return it.

    This is a heuristic, and a known weak spot: a long answer may be cut
    short, and a silent executor makes this hang until the timeout.
    """
    started = time.time()
    previous = ""
    while time.time() - started < timeout:
        current = said_after(session, since)
        if current and current == previous and len(current) > SETTLED_MIN:
            return current
        previous = current
        time.sleep(POLL)
    return previous


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    command = argv[0]

    if command == "windows":
        for window in windows.живые():
            print(f"  {window['id']}  {window.get('название', '')[:50]}")
        print(f"  chosen: {target_window() or '-'}")
        return 0

    if command == "send":
        delivered, session, detail = send(argv[1])
        print(f"{'delivered' if delivered else 'NOT DELIVERED'}: "
              f"window {session[:8]}  {detail}")
        return 0 if delivered else 1

    if command == "read":
        since = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 0
        session = argv[2] if len(argv) > 2 else target_window()
        print(said_after(session, since) or "(nothing)")
        return 0

    if command == "round":
        delivered, session, detail = send(argv[1])
        if not delivered:
            print(f"NOT DELIVERED: {detail}")
            return 1
        print(f"sent to window {session[:8]}, waiting...", file=sys.stderr)
        reply = wait_for_reply(session, int(detail))
        print(reply or "(no reply within timeout)")
        return 0 if reply else 1

    print(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
