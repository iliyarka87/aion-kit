# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-19

First working version.

### Added
- `src/link.py` — local delivery into a live executor window over an
  `AF_UNIX` socket, and reading the reply from a pre-send transcript mark.
- `src/director.py` — decide, dispatch and judge, driving the checklist gate
  without bypassing any of its rules.
- MIT license, README with the weak spots stated plainly.

### Verified
- The director read the board on its own, took the next item, read its
  acceptance criteria and wrote a brief for the executor. No network.
- `link.py windows` lists live windows and the chosen one.
- The three local helpers this builds on make zero network calls — checked
  by inspection.

### Not yet verified
- A full round with a recorded verdict has not been run end to end.

### Replaced
An earlier transport carried the same messages through a repository and a
browser window. Over one day it lost 32 deliveries to a missing input field
and 18 to a busy transport lock. None of those failure modes exist here:
there is nothing between the two agents to fail.
