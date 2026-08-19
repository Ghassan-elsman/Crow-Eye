# The Windows registry transaction log

### What `.LOG1` and `.LOG2` are, what the sequence numbers mean, and a gap that took a reference implementation to settle

Most forensic tooling treats a registry hive as a file you open and read. It usually is. But a hive
that Windows had open when the image was taken is, more often than not, **not the final state of
that registry** — and the missing part is sitting in a file right next to it that most tools never
touch.

This is a walk through that mechanism: what the log files are, how they relate to the hive, what the
two sequence numbers in a hive header actually mean, and an investigation into a discrepancy that
could not be resolved by reading the bytes alone. Every number here was measured on one running
Windows 11 machine, from hives captured in a single Volume Shadow Copy snapshot, and can be
reproduced.

---

## 1. The registry is a set of files

The registry is presented as a single tree — `HKEY_LOCAL_MACHINE`, `HKEY_CURRENT_USER` and the rest —
but that tree is a runtime assembly. On disk it is a handful of ordinary files, called **hives**, and
nothing more:

| hive file | where it lives | what it holds |
|---|---|---|
| `SYSTEM` | `C:\Windows\System32\config\` | hardware, services, drivers, mounted devices |
| `SOFTWARE` | `C:\Windows\System32\config\` | installed applications, OS configuration |
| `SAM` | `C:\Windows\System32\config\` | local accounts |
| `SECURITY` | `C:\Windows\System32\config\` | LSA policy, secrets |
| `DEFAULT` | `C:\Windows\System32\config\` | the profile applied before anyone logs on |
| `NTUSER.DAT` | `C:\Users\<user>\` | one per user: their settings and activity |
| `UsrClass.dat` | `C:\Users\<user>\AppData\Local\Microsoft\Windows\` | per-user shell state, including Shellbags |

`HKEY_LOCAL_MACHINE\SYSTEM` is the `SYSTEM` file mounted at a name. `HKEY_USERS\<SID>` is that user's
`NTUSER.DAT`, mounted while they are logged on and unmounted when they are not. The tree is a view;
the files are the evidence.

Inside, a hive is a **base block** — 4096 bytes of header — followed by **hive bins**, which are
containers of **cells**. A cell holds a key, a value, a list of subkeys, or a security descriptor.
Keys reference other cells by offset. That last point matters more than it sounds: a hive is a graph
of offsets, and a structure that points at a cell which was never written is not a slightly damaged
hive, it is an unreadable one.

### The base block, decoded

Here is the real first 48 bytes of the `SYSTEM` hive from the machine used throughout, field by
field:

| offset | field | value |
|---|---|---|
| `0x00` | signature | `regf` |
| `0x04` | **Sequence1** | 1888230 |
| `0x08` | **Sequence2** | 1888229 |
| `0x0C` | last-written timestamp (FILETIME) | `0` |
| `0x14` | major version | 1 |
| `0x18` | minor version | 5 |
| `0x1C` | file type | 0 (primary) |
| `0x20` | file format | 1 |
| `0x24` | root cell offset | `0x20` |
| `0x28` | hive bins data size | 23,826,432 |
| `0x2C` | clustering factor | 1 |
| `0x30` | file name (64 bytes, UTF-16) | `SYSTEM` |
| `0x1FC` | checksum | `0x6D9341D4` |

Two asides worth having. The **last-written timestamp at `0x0C` is zero** — not just on `SYSTEM`, but
on `NTUSER.DAT` and `SAM` as well. It is a documented field and modern Windows does not appear to
maintain it, so it is not a timestamp to build anything on. And the **checksum at `0x1FC`** is a
plain XOR of the 127 32-bit words before it, with `0` and `0xFFFFFFFF` nudged by one because both are
reserved — get that wrong when you write a hive back and every tool will reject the file.

The two fields in bold are the subject of this article.

---

## 2. Why a file like this needs a journal

Consider something trivial: an application writes a registry value.

That is not one write. The value's cell may need to grow, so it is reallocated somewhere else in the
bin. The parent key's value list must be updated to point at the new location. The old cell is
released back into free space, which updates allocation bookkeeping. A bin may need to be extended.
Several pages of the file change, and they only make sense **together**.

Now interrupt it. Power loss, a forced reset, a snapshot taken at exactly the wrong moment. Some of
those pages reached the disk and some did not. The result is a hive whose key list points at a cell
that was never written — a graph with an edge to nothing.

For a file that Windows writes to constantly and cannot function without, "sometimes it is corrupt
after a crash" is not survivable. So the registry does what databases and journalling filesystems do:
**it writes its intentions down somewhere else first.** That somewhere else is the transaction log.

---

## 3. The two sequence numbers

The mechanism is a pair of counters in the base block: `Sequence1` at `0x04` and `Sequence2` at
`0x08`.

The protocol is:

1. **Raise `Sequence1`** and flush the base block. The hive now says: *a write is in progress.*
2. **Write the changed pages.**
3. **Set `Sequence2` to match** and flush again. The hive now says: *the write completed.*

The consequence is the whole point. If a crash happens anywhere between steps 1 and 3, the numbers on
disk are **unequal**, and any reader can detect it with two reads and a comparison:

```
Sequence1 == Sequence2   ->  the hive was closed cleanly
Sequence1 != Sequence2   ->  a write was in flight; the log holds the rest
```

This is the field every tool means when it says "dirty hive". It is not a heuristic or a guess — it
is one comparison of two integers, and it is why two counters exist rather than one. A single
counter could say *how many* writes had happened, but not whether the current one had finished.

### What this looks like on a live machine

Seven hives, captured in one snapshot:

| hive | Sequence1 | Sequence2 | state |
|---|---|---|---|
| SYSTEM | 1888230 | 1888229 | **dirty** |
| SOFTWARE | 5102671 | 5102670 | **dirty** |
| NTUSER.DAT | 365687 | 365686 | **dirty** |
| UsrClass.dat | 251613 | 251612 | **dirty** |
| DEFAULT | 197479 | 197478 | **dirty** |
| SAM | 382 | 382 | clean |
| SECURITY | 1069 | 1069 | clean |

Five of seven are dirty, and every dirty one is dirty by **exactly one**. That is not coincidence and
it is not five interrupted writes. It is the ordinary steady state of a machine that is running: the
busy hives are perpetually mid-transaction, because there is always another write.

The two clean ones are the two nobody writes to. `SAM` has been written 382 times in the life of this
installation; `SYSTEM` has been written 1.8 million times. Account databases change when accounts
change. `SYSTEM` changes when anything happens at all.

**The practical reading for an examiner: on a live-acquired image, expect the interesting hives to be
dirty.** It is the normal condition, not a sign of damage or of anti-forensics.

---

## 4. The log files

Next to every hive sit two more files with the same name and the extensions `.LOG1` and `.LOG2`.
`C:\Windows\System32\config\` holds `SYSTEM`, `SYSTEM.LOG1`, `SYSTEM.LOG2`, and the same for the
others. They are the journal.

There are two formats.

**The old format**, used up to Windows 7, marks its dirty data with a `DIRT` signature. It still turns
up in older images.

**The new format**, from Windows 8.1 onwards, is what this article is about. A new-format log file
is:

```
offset 0     a 512-byte copy of the hive's base block
offset 512   the first log entry  ("HvLE")
             the second log entry
             ...
             unused space (see §6 - it is not empty)
```

The base block copy at the front is the log's own header, and it carries **its own sequence number**.
Remember that: it becomes the crux of the whole investigation.

Two things a parser must get right here. First, the log's base block is **512 bytes**, not the 4096
of a primary hive — read the first entry at 4096 and you will find nothing. Second, an old-format
`DIRT` log must be *recognised* so it can be refused. Reading a `DIRT` log with new-format offsets
does not throw an error; it reads plausible-looking garbage and applies it to the wrong parts of the
hive. Recognising a format you cannot handle is not the same as failing to recognise it.

---

## 5. Anatomy of a log entry

Each entry begins with a 40-byte header:

| offset | size | field |
|---|---|---|
| `0x00` | 4 | signature, `HvLE` |
| `0x04` | 4 | size of this entry (a multiple of 512) |
| `0x08` | 4 | flags |
| `0x0C` | 4 | **sequence number** |
| `0x10` | 4 | hive bins data size after this entry |
| `0x14` | 4 | dirty page count |
| `0x18` | 8 | hash-1 (Marvin32 over the entry body) |
| `0x20` | 8 | hash-2 (Marvin32 over the first 32 bytes) |

Then a **dirty page reference table** — one 8-byte pair per page, an offset and a size — and then the
page data itself, laid out back to back in the same order.

To apply an entry: walk the reference table, and for each `(offset, size)` pair take the next `size`
bytes of page data and write them into the primary hive at `4096 + offset`. The `4096` is the primary
file's base block; page offsets are relative to the start of the hive bins.

### These are page images, not deltas

That distinction decides how the whole scheme behaves, so it is worth measuring rather than assuming.
In `SYSTEM.LOG1`:

* every page offset is 4096-aligned;
* every page size is a multiple of 4096;
* across 53 entries there are **620 page writes to 149 distinct offsets** — an average of **4.2
  rewrites of the same page**;
* offset 0 — the first hive bin — appears in **all 53 entries**.

So an entry does not say "change these bytes"; it says "this page now looks exactly like this". A
later entry writing the same offset completely supersedes an earlier one. That first bin appears
every time because it holds the allocation bookkeeping that every transaction touches.

This is why entries must be applied **in sequence order** — last write wins — and it is why an
unbroken chain matters more than it might first appear.

---

## 6. A signature is not enough: the stale tail

Here is the trap that would catch a naive implementation, and the reason those two hashes are in
every entry.

**A log file is not truncated when it is reused.** Windows writes entries from offset 512 onward and
leaves whatever was there before in place beyond the last one. The tail of a log file is the previous
generation's entries — real, structurally valid, correctly hashed entries, that are simply *old*.

Measured on the same machine:

| log file | size | used | unused | stale `HvLE` signatures in the unused tail |
|---|---|---|---|---|
| `SYSTEM.LOG1` | 6,020,096 | 3,547,136 | 41% | 0 |
| `SYSTEM.LOG2` | 6,011,904 | 3,067,904 | 49% | **9** |
| `UsrClass.dat.LOG2` | 1,531,904 | 647,168 | 58% | **15** |

An implementation that scanned a log file for `HvLE` and applied everything it found would apply
**nine stale transactions** onto `SYSTEM` and **fifteen** onto `UsrClass.dat` — writing an older
generation's page images over a newer hive. It would not crash. It would produce a hive that opens
cleanly and is quietly wrong.

Two things prevent it:

1. **The sequence chain.** Entries run consecutively. Parsing stops at the first entry whose sequence
   number is not the one expected next. The stale tail does not continue the chain, so it is never
   reached.
2. **Marvin32.** Each entry carries two hashes: one over the entry body from offset 40, one over its
   first 32 bytes. Windows uses the seed `0x82EF4D887A4E55C5`. Both must reproduce, or the entry is
   not an entry.

Reproducing those hashes is also the best self-check available when implementing this. If your
Marvin32 and your header offsets are both right, the stored hashes come out exactly; if either is
wrong, they do not. It validates the algorithm and the layout in one step, before you have written a
single byte to a hive.

---

## 7. Why there are two logs

Windows alternates. It writes into one log until it switches, then continues into the other, so that
at any moment one of them holds a complete, applicable run.

Together the pair covers **one unbroken sequence range**. On this machine, for `SYSTEM`:

```
SYSTEM.LOG1   entries 1889322 .. 1889374   (53 entries,  620 pages)
SYSTEM.LOG2   entries 1889375 .. 1889408   (34 entries,  535 pages)
                      ^^^^^^^ continues exactly where LOG1 stopped
```

**Which file starts is not fixed.** For `UsrClass.dat` on the same machine it was the other way
round:

```
UsrClass.dat.LOG2   entries 251897 .. 251915
UsrClass.dat.LOG1   entries 251916 .. 251932
```

So the pair must be ordered by the sequence numbers inside them, never by filename. Assuming `.LOG1`
comes first works on most hives and silently produces the wrong result on the rest.

---

## 8. The challenge: a gap that should not be there

With the format understood, the implementation is mechanical: find the dirty hives, read the logs,
apply the entries in order, fix up the base block. The intent was simply to stop reporting a stale
registry as though it were final.

Then the numbers refused to make sense.

The recovery rule as commonly described is that log entries continue from where the hive left off. So
for `SYSTEM`, with `Sequence2` at 1,888,229, the first log entry should be 1,888,230.

It was **1,889,322** — 1,093 sequences further on. And it was not a one-off:

| hive | Sequence2 | first log entry | distance |
|---|---|---|---|
| SYSTEM | 1888229 | 1889322 | 1,093 |
| SOFTWARE | 5102670 | 5104537 | 1,867 |
| NTUSER.DAT | 365686 | 366244 | 558 |
| UsrClass.dat | 251612 | 251897 | 285 |
| DEFAULT | 197478 | 197940 | 462 |

Every dirty hive on the machine, hundreds to nearly two thousand transactions adrift.

The first suspicion was acquisition: three files copied at three different moments would explain it.
So they were re-copied from a **single** VSS snapshot, together. Identical numbers. The base block
checksums validated. This was the real on-disk state.

Which left two readings of the same bytes:

> **Reading A — the transactions are gone.** The log holds 1889322 onward; everything between the
> hive's position and there has been overwritten. The hive's state and the log's do not meet.
> Applying these entries writes page images onto a hive state they were never computed against,
> producing a file that looks valid and is subtly wrong. **A replay must refuse.**
>
> **Reading B — the base block simply lags.** The hive's body is further along than its header
> admits, and the log continues correctly from the real position. **A replay must apply.**

The two readings demand opposite implementations, and the wrong one damages evidence — either by
corrupting hives that were recoverable, or by discarding recoverable data on every case. There was no
way to tell from the file alone which was true.

### One hypothesis, tested and discarded

Reading B implies the hive's body is ahead of its base block. That is testable: the base block
declares the hive bins data size at `0x28`, so if the body had grown past what the header records,
the file would be larger than the header claims.

It is:

| hive | base block says | file actually holds | surplus |
|---|---|---|---|
| SYSTEM | 23,826,432 | 23,851,008 | +24,576 |
| SOFTWARE | 135,081,984 | 135,262,208 | +180,224 |
| NTUSER.DAT | 14,331,904 | 14,413,824 | +81,920 |

Encouraging — until the log entries were checked. **The last log entry declares the same hive bins
size as the base block**, not the larger figure. If the log's own final view of the hive matches the
header, the surplus is not un-recorded growth; it is space Windows pre-allocated and has not used.

The hypothesis predicted the log would disagree with the base block. It agreed. So it was wrong, and
the question was still open.

---

## 9. How it was settled

At this point the honest position is that the format documentation, the file, and reasoning about it
were all exhausted, and the remaining options were to guess or to find something that already knew
the answer.

The something is **`yarp`** — Maxim Suhanov's registry parser, and the reference implementation of
log recovery, from the same author as the published format specification. It shares no code with the
implementation being built, which is precisely what makes it useful: an independent answer to the
same question.

It was installed as a **development oracle only** — never a dependency of the shipping tool, never
imported by it — and pointed at the same hives.

It recovered all five without complaint.

That answers the question empirically: **Reading B is correct, the entries do apply.** And reading how
it decides reveals the rule that the common description of the algorithm glosses over:

> **Log entries chain from the log file's own base-block sequence number — not from the hive's.**
>
> A log file is eligible when its sequence is **at or ahead of** the hive's `Sequence2`. Only a log
> **older** than the hive is refused.

Look back at §4: the log file carries a 512-byte copy of the base block, with its own sequence number.
For `SYSTEM.LOG1` that number is 1,889,322 — exactly its first entry. The log is internally
consistent and self-describing. It was never claiming to continue from the hive; it states where it
begins, and the only thing the hive's sequence is used for is to reject a log that predates it.

The gap was never a gap. It was a chain being measured from the wrong end.

### Verifying rather than trusting

An oracle that gives the right answer is not the same as an implementation that is right. So the
requirement was set higher than "it works": for every hive, the two implementations had to produce a
**byte-identical** recovered file, or refuse for the same reason.

They did — five recovered identically, both declining the two clean hives. Seven agreements, no
disagreements, with every source file's SHA-256 unchanged either side of the run.

That check is now a permanent test, and it has been shown to fail for the right reason: reverting the
rule to the intuitive-but-wrong reading (requiring the log to continue from the hive's sequence)
makes it fail on all five hives with "ours refused, yarp recovered". A check nobody has seen fail is
a check nobody has reason to trust.

---

## 10. What replay actually recovers

Not a rounding error:

| hive | entries applied | pages written | keys gained | values gained | lost |
|---|---|---|---|---|---|
| SYSTEM | 87 | 1,155 | — | — | — |
| SOFTWARE | 250 | 3,905 | — | — | — |
| NTUSER.DAT | 69 | 1,082 | **+10** | **+4** | **0** |
| UsrClass.dat | 36 | 188 | **+1** | **+2** | **0** |
| DEFAULT | 17 | 233 | 0 | 0 | **0** |

(`SYSTEM` and `SOFTWARE` were not walked key-by-key — enumerating a 135 MB hive twice takes minutes —
but they applied the most data of all.)

Ten keys and four values in one user's `NTUSER.DAT`: recent activity, the most recent there is, and
precisely the part of a user hive an examiner cares about most. Without replay it is not "slightly
stale" — it is absent, with nothing to indicate anything is missing.

**Nothing was lost anywhere.** A replay that gains keys while losing none, and that matches an
independent implementation byte for byte, is a replay doing what it claims.

---

## 11. What is still not known

The rule is settled and the results verified. The mechanism behind the gap is not.

*Why* does Windows leave the hive's base block hundreds or thousands of sequences behind its log?
Reading B is confirmed by behaviour, but the reason is still open. The plausible candidates are that
the log is reinitialised at a point that does not update the primary's header, or that the primary is
flushed on a schedule independent of the base-block sequence. This article does not choose between
them, because nothing measured here distinguishes them — and one hypothesis in that family has
already been tested and failed (§8).

What would settle it: instrumenting hive flushes on a live system and watching both files change, or
kernel-side tracing of the registry writer. Neither is available from a snapshot.

Stating this matters more than tidying it away. The recovery is correct — that is established by
byte-identical agreement with the reference and by gaining data while losing none. The explanation
for one of its inputs is not, and an article that implied otherwise would be teaching a guess.

---

## 12. Why any of this matters

An offline registry parse that ignores the transaction logs reports a registry that is minutes to
hours behind the machine it came from — and gives no indication that it is doing so. On the machine
throughout this article, that is **five of seven hives**, including `SYSTEM`, `SOFTWARE` and the
user's `NTUSER.DAT`.

For an examiner the practical points are:

* **A dirty hive is normal**, not evidence of tampering or damage. Busy hives on a running machine are
  dirty essentially all the time.
* **The logs are evidence.** `.LOG1` and `.LOG2` belong in an acquisition alongside the hive. A
  collection that takes only the hive files has discarded the most recent registry activity — the
  part closest to whatever prompted the investigation.
* **"Recovered" needs saying out loud.** Whether a hive was replayed changes what its rows mean, so a
  tool should record per hive whether it was dirty, whether logs were present, and whether recovery
  ran. When it cannot recover, the right answer is to parse anyway and say so, not to fail silently
  in either direction.
* **Never write to the evidence.** Recovery produces a modified hive by definition. It belongs in a
  working copy, with the original opened read-only and its hash unchanged before and after.

---

### Reproducing this

Everything above comes from files any Windows machine has. The hives are locked while Windows runs,
so they must be read through a Volume Shadow Copy or raw disk access — and all of a hive's files must
come from **one** snapshot, or you will chase acquisition artefacts, as happened here.

From there: the sequence numbers are two `uint32` at `0x04` and `0x08`; the log's first entry is at
offset 512; the entry header is the 40 bytes in §5. A hex editor is enough to confirm every table in
this article.

---

*This came out of work on [Crow-Eye](https://crow-eye.com), an open-source Windows forensics engine,
where the registry parser now replays transaction logs before parsing and records what it did for
every hive. The implementation and its verification are open:
`Artifacts_Collectors/registry_transaction_log.py` and
`correlation_engine/tests/test_transaction_log_replay.py`. Credit to Maxim Suhanov, whose format
specification and `yarp` implementation are what made the question answerable rather than a matter of
opinion.*

*See also [`live-vs-offline.md`](live-vs-offline.md) for what a hive's recovery state means when
reading a parsed case.*
