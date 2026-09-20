#!/usr/bin/env python3
"""Probes for the activity observer.

Two kinds. Built fixtures pin every state down to the second, because a clock
that moves makes a probe that lies. Live replays then run the same parser over
the real journals on this disk, so the fixtures cannot drift into fiction.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import watch  # noqa: E402

# A fixed moment, so every probe is reproducible: 2026-09-19T23:25:00Z.
NOW = watch.to_epoch("2026-09-19T23:25:00Z")

LIVE_CODEX_THREAD = "01a0bbfc-8fdf-77b3-9a90-6569c9410160"
LIVE_CLAUDE_SESSION = "94b84116-71c1-4882-af73-479b0476709c"


def write_codex(root, thread_id, records):
    day = os.path.join(root, "2026", "09", "19")
    os.makedirs(day, exist_ok=True)
    path = os.path.join(day, "rollout-2026-09-19T23-24-46-%s.jsonl" % thread_id)
    with open(path, "w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def write_claude(root, session_id, records):
    project = os.path.join(root, "-Users-iliar")
    os.makedirs(project, exist_ok=True)
    path = os.path.join(project, "%s.jsonl" % session_id)
    with open(path, "w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def event(stamp, sub, **payload):
    payload["type"] = sub
    return {"timestamp": stamp, "type": "event_msg", "payload": payload}


def item(stamp, sub, **payload):
    payload["type"] = sub
    return {"timestamp": stamp, "type": "response_item", "payload": payload}


def said(stamp, kind, blocks, uuid=None):
    return {"timestamp": stamp, "type": kind, "uuid": uuid,
            "message": {"role": kind, "content": [{"type": b} for b in blocks]}}


class Time(unittest.TestCase):
    """Two clocks, one comparison. Mixing them is the trap this closes."""

    def test_z_and_offset_are_the_same_instant(self):
        self.assertEqual(watch.to_epoch("2026-09-19T23:24:47Z"),
                         watch.to_epoch("2026-09-19T19:24:47-04:00"))

    def test_naive_stamp_is_read_as_utc(self):
        self.assertEqual(watch.to_epoch("2026-09-19T23:24:47"),
                         watch.to_epoch("2026-09-19T23:24:47Z"))

    def test_local_output_always_carries_its_offset(self):
        text = watch.local_iso(NOW)
        self.assertTrue(text.endswith("Z") or "+" in text[10:] or "-" in text[10:],
                        "local time printed without an offset invites the mix-up")

    def test_utc_output_is_the_stamp_it_was_given(self):
        self.assertTrue(watch.utc_iso(NOW).startswith("2026-09-19T23:25:00"))

    def test_garbage_stamp_does_not_crash(self):
        self.assertIsNone(watch.to_epoch("not a time"))
        self.assertIsNone(watch.to_epoch(None))


class CodexStates(unittest.TestCase):
    """The four shapes the task named, replayed as codex writes them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def observe(self, thread_id, records, now=NOW):
        write_codex(self.root, thread_id, records)
        return watch.observe_codex(thread_id, now=now, root=self.root)

    def test_started_tool_completed_is_tool_activity(self):
        out = self.observe("T-TOOL", [
            {"timestamp": "2026-09-19T23:24:47Z", "type": "session_meta",
             "payload": {"session_id": "T-TOOL"}},
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:52Z", "custom_tool_call", name="exec"),
            item("2026-09-19T23:24:54Z", "custom_tool_call_output"),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1",
                  last_agent_message="ready"),
        ])
        self.assertEqual(out["state"], watch.TOOL_ACTIVITY)
        self.assertEqual(out["last_turn"]["tool_calls"], 1)
        self.assertTrue(out["last_turn"]["finished"])

    def test_message_without_any_tool_call_is_text_only(self):
        out = self.observe("T-TEXT", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:50Z", "message", role="assistant",
                 content=[{"type": "output_text", "text": "now I will gather myself"}]),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1",
                  last_agent_message="now I will gather myself"),
        ])
        self.assertEqual(out["state"], watch.TEXT_ONLY)
        self.assertEqual(out["last_turn"]["tool_calls"], 0)
        self.assertEqual(out["last_turn"]["assistant_messages"], 1)

    def test_prompt_text_from_the_harness_is_not_counted_as_the_agent_talking(self):
        out = self.observe("T-DEV", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:48Z", "message", role="developer",
                 content=[{"type": "input_text", "text": "system rules"}]),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1"),
        ])
        self.assertEqual(out["last_turn"]["assistant_messages"], 0)
        self.assertEqual(out["state"], watch.COMPLETED)

    def test_long_silence_after_completion_is_idle(self):
        out = self.observe("T-IDLE", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:52Z", "custom_tool_call", name="exec"),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1"),
        ], now=watch.to_epoch("2026-09-20T00:42:00Z"))          # an hour and a bit later
        self.assertEqual(out["state"], watch.IDLE)
        self.assertGreater(out["silence_seconds"], 4000)

    def test_idle_outranks_what_the_last_turn_happened_to_do(self):
        """An hour-old tool call does not make the agent busy now."""
        records = [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:52Z", "custom_tool_call", name="exec"),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1"),
        ]
        fresh = self.observe("T-RANK-A", records)
        stale = self.observe("T-RANK-B", records, now=watch.to_epoch("2026-09-20T00:42:00Z"))
        self.assertEqual(fresh["state"], watch.TOOL_ACTIVITY)
        self.assertEqual(stale["state"], watch.IDLE)

    def test_open_turn_still_moving_is_working(self):
        out = self.observe("T-OPEN", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:58Z", "custom_tool_call", name="exec"),
        ])
        self.assertEqual(out["state"], watch.WORKING)
        self.assertFalse(out["last_turn"]["finished"])

    def test_open_turn_gone_quiet_is_unknown_not_working(self):
        """A turn that opened and never closed must not shine a busy light forever."""
        out = self.observe("T-DEAD", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
        ], now=watch.to_epoch("2026-09-20T00:42:00Z"))
        self.assertEqual(out["state"], watch.UNKNOWN)
        self.assertIn("never closed", out["because"])


class ClaudeStates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def observe(self, session_id, records, now=NOW):
        write_claude(self.root, session_id, records)
        return watch.observe_claude(session_id, now=now, root=self.root)

    def test_growing_journal_is_working(self):
        out = self.observe("S-GROW", [
            said("2026-09-19T23:24:40Z", "user", ["text"], uuid="u1"),
            said("2026-09-19T23:24:50Z", "assistant", ["thinking", "tool_use"]),
            said("2026-09-19T23:24:58Z", "user", ["tool_result"]),
        ])
        self.assertEqual(out["state"], watch.WORKING)
        self.assertLessEqual(out["silence_seconds"], 90)

    def test_silence_is_idle(self):
        out = self.observe("S-QUIET", [
            said("2026-09-19T23:24:40Z", "user", ["text"], uuid="u1"),
            said("2026-09-19T23:24:50Z", "assistant", ["text"]),
        ], now=watch.to_epoch("2026-09-20T00:42:00Z"))
        self.assertEqual(out["state"], watch.IDLE)

    def test_a_tool_result_does_not_open_a_new_turn(self):
        out = self.observe("S-ONE", [
            said("2026-09-19T23:24:40Z", "user", ["text"], uuid="u1"),
            said("2026-09-19T23:24:45Z", "assistant", ["tool_use"]),
            said("2026-09-19T23:24:46Z", "user", ["tool_result"]),
            said("2026-09-19T23:24:50Z", "assistant", ["tool_use"]),
            said("2026-09-19T23:24:51Z", "user", ["tool_result"]),
        ])
        self.assertEqual(out["counts"]["turns_in_window"], 1)
        self.assertEqual(out["last_turn"]["tool_calls"], 2)

    def test_an_unfinished_turn_here_never_means_working(self):
        """This side has no end-of-turn marker, so only growth may say WORKING."""
        out = self.observe("S-NOMARK", [
            said("2026-09-19T23:24:40Z", "user", ["text"], uuid="u1"),
            said("2026-09-19T23:24:50Z", "assistant", ["text"]),
        ], now=watch.to_epoch("2026-09-19T23:27:30Z"))          # 160s: quiet, under idle
        self.assertIsNone(out["last_turn"]["completed_utc"])
        self.assertNotEqual(out["state"], watch.WORKING)
        self.assertEqual(out["state"], watch.TEXT_ONLY)


class Binding(unittest.TestCase):
    """The observer must look at a named thread, never at whatever is newest."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_thread_id_is_refused(self):
        for bad in (None, ""):
            with self.assertRaises(ValueError):
                watch.observe_codex(bad, now=NOW, root=self.root)
            with self.assertRaises(ValueError):
                watch.observe_claude(bad, now=NOW, root=self.root)

    def test_the_word_latest_is_not_a_thread_id(self):
        write_codex(self.root, "T-REAL", [event("2026-09-19T23:24:47Z", "task_started",
                                                turn_id="turn-1")])
        with self.assertRaises(FileNotFoundError):
            watch.observe_codex("latest", now=NOW, root=self.root)

    def test_the_named_thread_is_read_even_when_another_is_newer(self):
        write_codex(self.root, "T-WANTED", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            item("2026-09-19T23:24:50Z", "custom_tool_call", name="exec"),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1"),
        ])
        newer = write_codex(self.root, "T-OTHER", [
            event("2026-09-19T23:24:58Z", "task_started", turn_id="turn-9"),
        ])
        os.utime(newer, (NOW + 500, NOW + 500))
        out = watch.observe_codex("T-WANTED", now=NOW, root=self.root)
        self.assertIn("T-WANTED", out["evidence"]["path"])
        self.assertEqual(out["state"], watch.TOOL_ACTIVITY)


class ReadOnly(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def digest(path):
        import hashlib
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def test_observing_leaves_the_journal_byte_for_byte_identical(self):
        path = write_codex(self.root, "T-RO", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
            event("2026-09-19T23:24:55Z", "task_complete", turn_id="turn-1"),
        ])
        before = self.digest(path)
        before_mtime = os.path.getmtime(path)
        for _ in range(3):
            watch.observe_codex("T-RO", now=NOW, root=self.root)
        self.assertEqual(before, self.digest(path))
        self.assertEqual(before_mtime, os.path.getmtime(path))

    def test_evidence_carries_a_hash_of_exactly_what_was_read(self):
        path = write_codex(self.root, "T-HASH", [
            event("2026-09-19T23:24:47Z", "task_started", turn_id="turn-1"),
        ])
        out = watch.observe_codex("T-HASH", now=NOW, root=self.root)
        self.assertEqual(out["evidence"]["window_sha256"], self.digest(path))
        self.assertFalse(out["evidence"]["truncated"])

    def test_only_the_tail_is_read_on_a_big_file(self):
        records = [event("2026-09-19T23:%02d:%02dZ" % (20 + i // 60, i % 60),
                         "task_started", turn_id="turn-%d" % i) for i in range(300)]
        write_codex(self.root, "T-BIG", records)
        out = watch.observe_codex("T-BIG", now=NOW, root=self.root, tail_bytes=4000)
        self.assertTrue(out["evidence"]["truncated"])
        self.assertLessEqual(out["evidence"]["window_bytes"], 4000)
        self.assertGreater(out["counts"]["records_in_window"], 0)


class Loop(unittest.TestCase):
    """Both eyes at once. One side quiet is normal; both quiet is a stall."""

    def side(self, state, silence):
        return {"state": state, "silence_seconds": silence}

    def test_executor_working_is_not_a_stall_however_long_the_director_is_quiet(self):
        out = watch.loop_verdict(self.side(watch.IDLE, 5000),
                                 self.side(watch.WORKING, 3))
        self.assertEqual(out["loop_state"], "EXECUTOR_WORKING")
        self.assertFalse(out["stalled"])

    def test_director_working_is_not_a_stall(self):
        out = watch.loop_verdict(self.side(watch.WORKING, 2),
                                 self.side(watch.IDLE, 5000))
        self.assertEqual(out["loop_state"], "DIRECTOR_WORKING")
        self.assertFalse(out["stalled"])

    def test_both_quiet_past_the_threshold_is_a_stall(self):
        out = watch.loop_verdict(self.side(watch.TEXT_ONLY, 900),
                                 self.side(watch.IDLE, 800))
        self.assertEqual(out["loop_state"], "BOTH_QUIET")
        self.assertTrue(out["stalled"])

    def test_a_short_gap_between_turns_is_not_a_stall(self):
        out = watch.loop_verdict(self.side(watch.TOOL_ACTIVITY, 100),
                                 self.side(watch.TEXT_ONLY, 110))
        self.assertEqual(out["loop_state"], "BOTH_QUIET")
        self.assertFalse(out["stalled"])

    def test_the_verdict_says_out_loud_that_it_does_nothing(self):
        out = watch.loop_verdict(self.side(watch.IDLE, 9000), self.side(watch.IDLE, 9000))
        self.assertIn("no action", out["note"])


class LiveReplay(unittest.TestCase):
    """The same parser over the real journals, so the fixtures cannot drift."""

    def test_real_codex_journal_folds_into_turns(self):
        try:
            path = watch.codex_journal(LIVE_CODEX_THREAD)
        except FileNotFoundError:
            self.skipTest("live codex journal for %s is gone" % LIVE_CODEX_THREAD)
        out = watch.observe_codex(LIVE_CODEX_THREAD, now=NOW, path=path)
        self.assertIn(out["state"], watch.STATES)
        self.assertGreater(out["counts"]["turns_in_window"], 0)
        self.assertIsNotNone(out["last_event_utc"])
        self.assertEqual(len(out["evidence"]["window_sha256"]), 64)

    def test_a_real_codex_turn_shows_a_real_tool_call(self):
        try:
            path = watch.codex_journal(LIVE_CODEX_THREAD)
        except FileNotFoundError:
            self.skipTest("live codex journal is gone")
        records = watch.parse_lines(watch.read_tail(path)[0])
        turns, _ = watch.codex_turns(records)
        self.assertTrue(any(t["tool_calls"] > 0 for t in turns),
                        "expected at least one real turn that called a tool")
        self.assertTrue(all(t["completed_epoch"] is not None for t in turns),
                        "every started turn in this journal also completed")

    def test_real_claude_journal_folds_into_turns(self):
        try:
            path = watch.claude_journal(LIVE_CLAUDE_SESSION)
        except FileNotFoundError:
            self.skipTest("live claude journal is gone")
        out = watch.observe_claude(LIVE_CLAUDE_SESSION, now=NOW, path=path)
        self.assertIn(out["state"], watch.STATES)
        self.assertGreater(out["counts"]["records_in_window"], 0)
        self.assertTrue(out["evidence"]["truncated"], "a 60MB journal must be tail-read")

    def test_the_live_claude_journal_is_not_modified_by_looking_at_it(self):
        try:
            path = watch.claude_journal(LIVE_CLAUDE_SESSION)
        except FileNotFoundError:
            self.skipTest("live claude journal is gone")
        before = os.path.getmtime(path)
        watch.observe_claude(LIVE_CLAUDE_SESSION, now=NOW, path=path)
        self.assertEqual(before, os.path.getmtime(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
