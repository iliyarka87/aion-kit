#!/usr/bin/env python3
"""Probes for the watchman.

Every one runs with no director, no app-server and no message sent anywhere.
The rule and the target are the dangerous parts — a nudge at the wrong moment,
or into the wrong thread — so those are what get pinned down here.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import watch      # noqa: E402
import watchman   # noqa: E402

NOW = watch.to_epoch("2026-09-20T02:00:00Z")


def side(state, silence):
    return {"state": state, "silence_seconds": silence}


def fresh(strikes=0, last=None, stopped=False, asked=False):
    return {"strikes": strikes, "last_strike_epoch": last, "stopped": stopped,
            "asked_executor": asked}


def window(session, pid=1):
    return {"session": session, "pid": pid, "cwd": watchman.ROOT, "passport": "x.json"}


def thread(tid, updated):
    return {"thread": tid, "updated": updated, "status": "notLoaded", "preview": ""}


class ExecutorFirst(unittest.TestCase):
    """The clause the owner insisted on: watching one side only is no good."""

    def test_executor_working_silences_it_however_long_the_director_sleeps(self):
        action, reason, nxt = watchman.decide(
            side(watch.IDLE, 36000), side(watch.WORKING, 2), fresh(strikes=2), NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertIn("working", reason)
        self.assertEqual(nxt["strikes"], 0, "a working executor must zero the count")

    def test_a_long_job_does_not_accumulate_strikes(self):
        """Thirty minutes of building is normal and must cost nothing."""
        state = fresh()
        for minute in range(30):
            action, _, state = watchman.decide(
                side(watch.IDLE, 60 * minute + 600), side(watch.WORKING, 5),
                state, NOW + 60 * minute)
            self.assertEqual(action, watchman.NONE)
        self.assertEqual(state["strikes"], 0)

    def test_a_strike_already_spent_is_forgiven_when_the_executor_resumes(self):
        state = fresh(strikes=2, last=NOW - 400)
        _, _, state = watchman.decide(
            side(watch.IDLE, 9000), side(watch.WORKING, 1), state, NOW)
        self.assertEqual(state["strikes"], 0)
        self.assertIsNone(state["last_strike_epoch"])


class WhenItStrikes(unittest.TestCase):

    def test_both_quiet_past_three_minutes_is_a_strike(self):
        action, reason, nxt = watchman.decide(
            side(watch.TEXT_ONLY, 200), side(watch.IDLE, 400), fresh(), NOW)
        self.assertEqual(action, watchman.STRIKE)
        self.assertEqual(nxt["strikes"], 1)
        self.assertIn("strike 1 of 3", reason)

    def test_under_three_minutes_is_not_a_strike(self):
        action, reason, _ = watchman.decide(
            side(watch.TEXT_ONLY, 179), side(watch.IDLE, 400), fresh(), NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertIn("179s of 180s", reason)

    def test_the_director_mid_turn_is_never_struck(self):
        action, reason, _ = watchman.decide(
            side(watch.WORKING, 5), side(watch.IDLE, 9000), fresh(), NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertIn("mid-turn", reason)

    def test_three_minutes_must_pass_between_strikes(self):
        state = fresh(strikes=1, last=NOW - 100)
        action, reason, nxt = watchman.decide(
            side(watch.IDLE, 5000), side(watch.IDLE, 5000), state, NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertIn("waiting out", reason)
        self.assertEqual(nxt["strikes"], 1, "waiting must not spend a strike")

    def test_the_second_strike_lands_exactly_three_minutes_later(self):
        state = fresh(strikes=1, last=NOW - 180)
        action, _, nxt = watchman.decide(
            side(watch.IDLE, 5000), side(watch.IDLE, 5000), state, NOW)
        self.assertEqual(action, watchman.STRIKE)
        self.assertEqual(nxt["strikes"], 2)


class ThreeAndStop(unittest.TestCase):
    """No infinite echo. That was the owner's whole complaint."""

    def test_three_strikes_then_the_executor_is_asked_then_it_stops(self):
        """The owner's fourth step: stop calling the director, ask the executor."""
        state = fresh()
        for expected in (1, 2, 3):
            action, _, state = watchman.decide(
                side(watch.IDLE, 5000), side(watch.IDLE, 5000), state, NOW + 200 * expected)
            self.assertEqual(action, watchman.STRIKE)
            self.assertEqual(state["strikes"], expected)

        action, reason, state = watchman.decide(
            side(watch.IDLE, 5000), side(watch.IDLE, 5000), state, NOW + 1000)
        self.assertEqual(action, watchman.ASK_EXECUTOR)
        self.assertTrue(state["asked_executor"])
        self.assertFalse(state.get("stopped"))
        self.assertIn("why the director went quiet", reason)

        action, reason, state = watchman.decide(
            side(watch.IDLE, 5000), side(watch.IDLE, 5000), state, NOW + 2000)
        self.assertEqual(action, watchman.STOP)
        self.assertTrue(state["stopped"])
        self.assertIn("owner", reason)

    def test_the_executor_is_asked_once_and_not_in_a_loop(self):
        state = fresh(strikes=3, last=NOW - 5000, asked=True)
        for step in range(4):
            action, _, state = watchman.decide(
                side(watch.IDLE, 9000), side(watch.IDLE, 9000), state, NOW + 1000 * step)
            self.assertEqual(action, watchman.STOP)

    def test_a_working_executor_is_never_asked_anything(self):
        """If it were working, none of this would be happening."""
        state = fresh(strikes=3, last=NOW - 5000)
        action, _, state = watchman.decide(
            side(watch.IDLE, 9000), side(watch.WORKING, 2), state, NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertFalse(state["asked_executor"])
        self.assertEqual(state["strikes"], 0)

    def test_once_stopped_it_stays_stopped(self):
        state = fresh(strikes=3, last=NOW - 5000, stopped=True, asked=True)
        for step in range(5):
            action, _, state = watchman.decide(
                side(watch.IDLE, 9000), side(watch.IDLE, 9000), state, NOW + 1000 * step)
            self.assertEqual(action, watchman.STOP)

    def test_the_executor_coming_back_clears_a_stop_and_the_ask(self):
        state = fresh(strikes=3, last=NOW - 5000, stopped=True, asked=True)
        action, _, state = watchman.decide(
            side(watch.IDLE, 9000), side(watch.WORKING, 2), state, NOW)
        self.assertEqual(action, watchman.NONE)
        self.assertFalse(state["stopped"])
        self.assertFalse(state["asked_executor"])
        self.assertEqual(state["strikes"], 0)

    def test_the_question_to_the_executor_names_the_task_not_the_mood(self):
        self.assertIn("Выясни, почему", watchman.ASK_PHRASE)
        self.assertIn("владельцу", watchman.ASK_PHRASE)


class WhatCountsAsSuccess(unittest.TestCase):
    """Not the director's reply. A message in the executor's window."""

    def test_a_message_that_landed_clears_the_count(self):
        state = fresh(strikes=2, last=NOW - 200)
        action, reason, nxt = watchman.decide(
            side(watch.TEXT_ONLY, 300), side(watch.IDLE, 300), state, NOW, delivered=True)
        self.assertEqual(action, watchman.NONE)
        self.assertIn("landed", reason)
        self.assertEqual(nxt["strikes"], 0)

    def test_talking_without_delivering_does_not_clear_the_count(self):
        """TEXT_ONLY is exactly 'now I will gather myself'. It buys nothing."""
        state = fresh(strikes=1, last=NOW - 200)
        action, _, nxt = watchman.decide(
            side(watch.TEXT_ONLY, 200), side(watch.IDLE, 300), state, NOW, delivered=False)
        self.assertEqual(action, watchman.STRIKE)
        self.assertEqual(nxt["strikes"], 2)


class ThePhrase(unittest.TestCase):

    def test_it_is_the_owners_exact_words_and_is_not_a_question(self):
        self.assertEqual(watchman.PHRASE, "Напиши Клоду следующее действие")
        for hedge in ("?", "чей", "ход", "планируй"):
            self.assertNotIn(hedge, watchman.PHRASE)

    def test_the_thresholds_are_the_three_numbers_the_owner_named(self):
        self.assertEqual(watchman.QUIET_BEFORE_STRIKE, 180)
        self.assertEqual(watchman.BETWEEN_STRIKES, 180)
        self.assertEqual(watchman.MAX_STRIKES, 3)


class WhoIsWho(unittest.TestCase):
    """Nobody should type session ids, and nothing should be guessed."""

    def test_one_live_window_and_one_thread_is_a_confident_pair(self):
        found = watchman.detect(windows=[window("S-1")],
                                threads=[thread("T-1", 1000)])
        self.assertTrue(found["confident"])
        self.assertEqual(found["claude_session"], "S-1")
        self.assertEqual(found["codex_thread"], "T-1")

    def test_two_live_windows_refuses_rather_than_guesses(self):
        found = watchman.detect(windows=[window("S-1", 1), window("S-2", 2)],
                                threads=[thread("T-1", 1000)])
        self.assertFalse(found["confident"])
        self.assertIsNone(found["claude_session"])
        self.assertIn("2 live executor windows", " ".join(found["why"]))

    def test_no_live_window_refuses(self):
        found = watchman.detect(windows=[], threads=[thread("T-1", 1000)])
        self.assertFalse(found["confident"])
        self.assertIn("no live executor window", " ".join(found["why"]))

    def test_no_director_thread_here_refuses(self):
        found = watchman.detect(windows=[window("S-1")], threads=[])
        self.assertFalse(found["confident"])
        self.assertIn("no director thread", " ".join(found["why"]))

    def test_the_newest_thread_wins_when_it_is_clearly_newest(self):
        found = watchman.detect(windows=[window("S-1")],
                                threads=[thread("T-NEW", 9000), thread("T-OLD", 1000)])
        self.assertTrue(found["confident"])
        self.assertEqual(found["codex_thread"], "T-NEW")

    def test_two_threads_touched_close_together_is_not_confident(self):
        """Newest-wins is fine when it is obvious, and a coin flip when it is not."""
        found = watchman.detect(windows=[window("S-1")],
                                threads=[thread("T-A", 9000), thread("T-B", 8800)])
        self.assertFalse(found["confident"])
        self.assertIn("200s apart", " ".join(found["why"]))


class Resolving(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.real_pair, self.real_detect = watchman.PAIR, watchman.detect
        watchman.PAIR = os.path.join(self.tmp.name, "pair.json")
        watchman.detect = lambda **k: {"claude_session": "S-DETECTED",
                                       "codex_thread": "T-DETECTED",
                                       "confident": True, "why": []}

    def tearDown(self):
        watchman.PAIR, watchman.detect = self.real_pair, self.real_detect
        self.tmp.cleanup()

    def test_with_nothing_pinned_it_detects(self):
        pair = watchman.resolve()
        self.assertEqual(pair["claude_session"], "S-DETECTED")
        self.assertEqual(pair["how"], "detected")

    def test_a_pin_beats_detection(self):
        watchman.save(watchman.PAIR, {"codex_thread": "T-PINNED",
                                      "claude_session": "S-PINNED"})
        pair = watchman.resolve()
        self.assertEqual(pair["codex_thread"], "T-PINNED")
        self.assertEqual(pair["how"], "pinned")

    def test_an_argument_beats_the_pin(self):
        watchman.save(watchman.PAIR, {"codex_thread": "T-PINNED",
                                      "claude_session": "S-PINNED"})
        pair = watchman.resolve(thread="T-ARG", session="S-ARG")
        self.assertEqual(pair["codex_thread"], "T-ARG")
        self.assertEqual(pair["how"], "argument")


class Blind(unittest.TestCase):
    """Not knowing who is who must stop the hand, not steer it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []
        self.saved = {name: getattr(watchman, name) for name in
                      ("STATE", "PAIR", "LEDGER", "strike", "resolve",
                       "still_there", "landed_in_window")}
        self.saved_watch = (watch.observe_codex, watch.observe_claude)
        watchman.STATE = os.path.join(self.tmp.name, "state.json")
        watchman.PAIR = os.path.join(self.tmp.name, "pair.json")
        watchman.LEDGER = os.path.join(self.tmp.name, "ledger.ndjson")
        watchman.strike = lambda *a, **k: (self.sent.append(a), {"delivered": True})[1]
        watchman.still_there = lambda pair: []
        watchman.landed_in_window = lambda *a, **k: False
        watch.observe_codex = lambda t, now, **k: dict(side(watch.IDLE, 9000), identity=t)
        watch.observe_claude = lambda s, now, **k: dict(side(watch.IDLE, 9000), identity=s)

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(watchman, name, value)
        watch.observe_codex, watch.observe_claude = self.saved_watch
        self.tmp.cleanup()

    def confident(self, yes):
        watchman.resolve = lambda t=None, s=None: {
            "codex_thread": "T", "claude_session": "S", "how": "detected",
            "confident": yes, "why": [] if yes else ["two live executor windows"]}

    def test_an_unsure_pair_never_strikes_even_when_armed(self):
        self.confident(False)
        out = watchman.tick(NOW, armed=True)
        self.assertEqual(out["action"], watchman.BLIND)
        self.assertEqual(self.sent, [], "unsure must send nothing")
        self.assertEqual(watchman.load_state()["strikes"], 0)

    def test_a_dead_window_stops_the_hand(self):
        self.confident(True)
        watchman.still_there = lambda pair: ["executor window S is not alive"]
        out = watchman.tick(NOW, armed=True)
        self.assertEqual(out["action"], watchman.BLIND)
        self.assertIn("not alive", out["reason"])
        self.assertEqual(self.sent, [])

    def test_without_arm_nothing_is_sent_and_no_strike_is_spent(self):
        self.confident(True)
        for step in range(4):
            out = watchman.tick(NOW + 400 * step, armed=False)
            self.assertEqual(out["action"], watchman.STRIKE)
        self.assertEqual(self.sent, [])
        self.assertEqual(watchman.load_state()["strikes"], 0)
        self.assertFalse(watchman.load_state()["stopped"])

    def test_with_arm_it_sends_once_and_spends_one_strike(self):
        self.confident(True)
        out = watchman.tick(NOW, armed=True)
        self.assertEqual(out["action"], watchman.STRIKE)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(watchman.load_state()["strikes"], 1)

    def test_every_tick_is_written_down(self):
        self.confident(True)
        watchman.tick(NOW, armed=False)
        with open(watchman.LEDGER, encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().strip().split("\n")), 1)


class LivePairing(unittest.TestCase):
    """Against this machine as it is right now."""

    def test_this_very_window_is_found_by_its_passport(self):
        found = watchman.live_windows()
        self.assertTrue(found, "no live executor window — this session is one")
        mine = os.environ.get("CLAUDE_SESSION_ID")
        if mine:
            self.assertIn(mine, [w["session"] for w in found])

    def test_a_dead_passport_is_not_counted_as_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "99999999.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"sessionId": "S-GHOST", "pid": 99999999}, handle)
            self.assertEqual(watchman.live_windows(tmp), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
