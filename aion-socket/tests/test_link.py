"""Probes for AION Socket. They read; they never deliver a live message."""
import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
spec = importlib.util.spec_from_file_location("link", SRC / "link.py")
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


class LinkProbes(unittest.TestCase):

    def test_no_network_imports(self):
        """The link must not reach the internet. Sockets are AF_UNIX only."""
        text = (SRC / "link.py").read_text(encoding="utf-8")
        for forbidden in ("import requests", "urllib.request", "http.client",
                          "AF_INET", "https://", "http://"):
            self.assertNotIn(forbidden, text, f"found {forbidden}")

    def test_director_never_writes_done(self):
        """Only the gate writes DONE. The director must not shortcut it."""
        text = (SRC / "director.py").read_text(encoding="utf-8")
        self.assertNotIn('"DONE"', text)
        self.assertIn('gate("validate"', text.replace("'", '"'))

    def test_mark_is_taken_before_send(self):
        """Old speech must never be read as a fresh reply."""
        text = (SRC / "link.py").read_text(encoding="utf-8")
        before = text.index("before = mark(session)")
        after = text.index("mailbox.послать")
        self.assertLess(before, after, "mark must be taken before sending")

    def test_target_window_falls_back(self):
        """With no chosen window, the freshest live one is used."""
        self.assertTrue(callable(link.target_window))
        self.assertIsInstance(link.target_window(), str)

    def test_reply_needs_to_settle(self):
        """A reply is only final once it stops growing."""
        self.assertGreater(link.SETTLED_MIN, 0)
        self.assertGreater(link.REPLY_TIMEOUT, link.POLL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
