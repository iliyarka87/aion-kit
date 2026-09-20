# The transport this project replaced

Written 2026-09-19, while the old channel was still running, so the account
comes from the machine rather than from memory.

For three days two coding agents on one Mac talked to each other through a
git repository and a browser window. It worked, in the sense that messages
arrived. It is worth writing down because everything that was wrong with it
is the reason the current project exists, and because the same design keeps
suggesting itself to anyone who has two agents and no obvious way to connect
them.

## The shape of it

Four moving parts, all on the same machine, none of them talking to each
other directly.

```
executor finishes a turn
   │
   ├─ 1. stop hook   reads the turn out of the session journal,
   │                 writes LAST-TURN.md and an archive entry,
   │                 calls the sync script, then drives a browser
   │                 to type one line into the director's chat window
   │
   ├─ 2. postman     pushes the repository to GitHub, every five
   │                 minutes and on every file change
   │
   ├─ 3. director    reads the repository, writes its answer back
   │                 into the repository
   │
   ├─ 4. pickup      polls GitHub every five seconds for a new task
   │                 and delivers it into the executor's window
   │
   └─ 5. guardian    writes a health summary into the repository
                     every thirty seconds
```

Every hop is a file. Two agents sitting in the same process table, on the
same disk, under the same user account, were sending each other messages via
a server on another continent.

## What it cost, measured

- **8038 commits** in the repository, of which **331** carried nothing but
  conversation transcript.
- **330 archive files, 1.9 MB**, accumulated in three days.
- The guardian alone produced **a commit every thirty seconds**, around the
  clock, whether or not anything had happened.
- The browser step waited **40 seconds** for a text field that was no longer
  there, on every single turn, and then failed. It had been failing for some
  time before anyone noticed, because a failure at that step looks exactly
  like the director simply not answering.
- Over one day the channel lost **32 deliveries** to that missing input field
  and **18** to a busy transport lock.

## Why each part was a mistake

**The repository as a message queue.** Git is built to preserve history, and
a message queue wants the opposite. Every turn of a private conversation
became a permanent commit. Deleting them later means rewriting 8038 commits
of history, which is a far larger operation than the messages ever were.

**The browser as a doorbell.** The only reason a browser was involved is
that one agent lived behind a web page. So a DOM selector, `#prompt-textarea`,
became load-bearing infrastructure. It broke the moment the page changed, and
it broke silently.

**A health reporter that reports into the transport.** The guardian wrote its
summary into the same repository the channel used, so watching the channel
made the channel busier. Most of the traffic on the wire was the wire
describing itself.

**Polling a remote for a local fact.** The pickup asked GitHub every five
seconds whether the process on the next core had said anything.

## What was actually right

Worth keeping, because these survived into the current design:

- **A marker in the message, not in a file.** The outcome of a task was read
  from the agent's own words (`TASK_OK T-SOMETHING`), not from a status file
  it might forget to write.
- **An append-only ledger.** Nothing in the channel could edit its own past.
- **The executor never grading itself.** A separate gate held that rule, and
  it held it mechanically rather than on trust.
- **Honest failure states.** `BLOCKED` meant blocked and was reported as
  such, including when the blocker was the owner's own security.

## The replacement, in one line

Both agents run on one machine, so they are connected by an `AF_UNIX` socket:
no network, no port, no route off the disk, no history to clean up later. See
the project README.

## The part that did not need replacing

None of this was an argument against the *mechanism* — the code for the old
channel is intact and is not deleted along with its transcripts. What it is
an argument against is choosing a transport because it is the one you already
have credentials for.
