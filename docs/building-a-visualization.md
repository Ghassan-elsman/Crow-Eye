# Building a visualization, or changing one

Canonical, and mirrored into the EXE tree. The sibling document for parsers is
`changing-a-parser.md`; this one covers the React dashboards under `visualizations/`.

Everything below was paid for. The traps in section 4 each cost real time, and every one of them
looked like something else first.

---

## 1. The shape of a dashboard

Four pieces, named consistently:

| | |
|---|---|
| `visualizations/<name>_bridge.py` | The data. A `QObject` whose public methods are `@pyqtSlot(str, result=str)` — **JSON string in, JSON string out**. Never returns a Python object. |
| `visualizations/<name>_dialog.py` | The window. Builds a `QWebChannel`, registers the bridge as `"bridge"`, loads the built page. |
| `visualizations/react-<name>/src/` | The front end. Vite + React. |
| `visualizations/react-<name>/dist/index.html` | **What the dialog actually loads** — a single self-contained file (vite-plugin-singlefile). |

**`npm run build`, or nothing changes.** Editing `src/` and reopening the dialog shows you the old
bundle. This is the single most common way to spend twenty minutes on a fix that already worked.

A new dashboard also needs adding to `build_exe.py`'s `apps` list, or the packaged build ships a
stale bundle.

---

## 2. What you will be duplicating, and why that is accepted

The six dashboards share **class names, not code**. There is no `shared/`, no component library and
no common stylesheet: `styles.css` is six divergent forks of one file that still line up
line-for-line. A fix applied to one is a fix applied to one.

These files are duplicated deliberately and **must stay byte-identical** — guarded by
`tests/test_dashboard_css_contracts.py`, `tests/test_insights_carry_their_subjects.py` and
`tests/test_dense_time_axis.py`:

`Icons.jsx` · `DateDropdown.jsx` · `DayAxis.jsx` · `InsightPanel.jsx` · `FullRecordSection.jsx` ·
`LoadingOverlay.jsx`

`DayAxis.jsx` is the one that carries behaviour rather than markup: it owns the strip's geometry
and window (`useStripFit`, `useStripWindow`, `windowFor`, `WINDOW_DAYS`), the `StripNavigator`,
and the date scale. Strip geometry goes there, not into six copies.

Python **is** shared, and new shared behaviour belongs there rather than in six copies:

- `visualizations/insights.py` — the insight shape
- `visualizations/raw_record.py` — the full-record shape, the `source_records()` list, and the
  withhold list that keeps stored passwords and cookie values off the screen
- `visualizations/timeseries.py` — filling the day range, so no strip erases a quiet one

---

## 3. The contracts

**The heat map is a horizontal day strip.** X is the day, Y is the series; the height is
`series × 38px` (a 34px cell plus the strip gap) whatever the range. SRUM and Browser were GitHub-style week calendars that grew
*downward* — Browser's 226 days were ~33 stacked rows, so the heat map owned the page and pushed
everything below the fold. Use the `.usn-strip` markup and `<DayAxis>` for the date scale.

**Every day in the range is a cell, including the empty ones.** A `GROUP BY date(...)` returns only
the days that *had* activity, and plotting that directly stops the x-axis being time: it becomes an
ordinal index of active days, where two neighbouring cells can be months apart while `DayAxis`
spaces its labels evenly across them. Measured before this was fixed — browser 134 cells across
**226** days, prefetch 170 across **213**, shellitems 146 across **4,568**. A quiet stretch is
usually the thing an investigator came to find. `visualizations/timeseries.py` fills the range:
`axis_range()` then `densify()` / `densify_series()` / `densify_table()`.

**One cell is one day. Always — a long range is paged six months at a time; it neither changes
the unit nor scrolls.** An intermediate version widened the cell to a week or a month so a
twelve-year range would fit, and Shell Items became 151 month cells — a different question
answered. The next version kept one day per cell and made the strip a ~23,000px horizontal
scroller: 7px slivers, no sense of the whole range, and dragging the only way around.

Now the strip shows a window of `WINDOW_DAYS` (183) days that always fills its pane
(`useStripWindow` + `useStripFit`; tracks are `minmax(0, 1fr)`, nothing scrolls). Above it,
`<StripNavigator win days totals>` pages the window (Previous / Next six months, Latest, ← / →) and
draws the **whole range** as an overview at one bar per week, the visible six months boxed; a click
anywhere in the overview moves the window there. The overview is labelled as the coarser thing it
is — the strip itself stays one cell per day. A range of 183 days or fewer is shown whole, with no
navigator. The axis labels month starts ("Jan 2026" at a year change, the 15th when there is room)
and never overprints.

**The strip opens on the most recent six months**, and the default selection is the last cell that
carries anything — not the busiest, which on a twelve-year range can be years away. A selection made
elsewhere (an insight, an item) moves the window to it only when it is off screen; `windowFor()` is
pure and tested in node.

**Every clickable surface opens something.** A table row, a chart segment, a heat-map cell, an
insight tile, an hour bar. If a thing can be clicked it leads somewhere — and a chart that renders
bars *looks* clickable whether or not anyone wired `onClick`, which is how four of the six shipped
an hour chart that did nothing.

**An hour bar opens that hour.** `<HourDetailPanel>` filters the day payload's own `events` by
`e.hour`; it makes no bridge call, because every day payload already carries a per-event `hour`
beside the `byHour` histogram the chart is drawn from. Render it in the **same component that owns
the state opening it** — five keep both in `App`, `react-viz` keeps both in `DayActivitySection`;
either is fine, a split is not, because then the state can be set while the panel is unmounted.
Note this is a *weaker* rule than the one for detail modals, which must live in `App`: an insight
can open a record with no day selected, an hour bar cannot.

**A detail panel shows the curated reading *and* the records behind it.** The curated view is the
interpretation — run-time history, volume block, resource list. `<FullRecordSection>` underneath
shows the source data, collapsed by default. Without it an analyst cannot tell "this artifact does
not record that" from "this panel does not show it". Two shapes, because the artifacts are two
shapes:

- `raw={detail?.raw}` — **one** source row (prefetch file, MFT entry, shell item). Every column of
  that row.
- `records={detail?.records}` — `raw_record.source_records()`, for a subject assembled from several.
  An LNK target is reached through `LNK_Files`, `Automatic_JumpLists`, `Custom_JumpLists` and
  `JLCE` at once; a SRUM app spans five providers; a browser domain spans every table that mentions
  it. Picking one of them would be *less* honest than showing all of them.

Use `detail?.` — `AppDetailPanel` guards on `!app`, not `!detail`, so a bare `detail.records` threw
while the modal was loading.

An aggregate panel must **count** its total rather than infer it from the rows it fetched:
`showing 40 of 600` where 600 was itself a `LIMIT` is still a wrong number on screen.

A shell item looked like it had no single row for years, because the comment saying so confused the
*dashboard* (which reads Shellbags, RecentDocs, OpenSaveMRU, TypedPaths) with an *item*, which is
one row of one of them.

**An insight carries its subjects, never a bare count.** Use `insights.insight(count, subjects)`,
and `insights.plain(count)` for a genuine measurement (a maximum, a distinct-user count) that has
no records behind it. A subject's `open` is the id that dashboard's detail modal already takes,
which is what makes an insight a drill-down rather than a number.

**A narrative card that ends in an unopenable number should become insight tiles.** Browser's
"Anti-forensics signals" listed orphan domains well and then finished with *"a further N domains
appear only in cache"* — a dead end. It was folded into an Insights card, and its reasoning became
the hint each tile carries, so the analyst reads it at the moment it matters rather than above a
list they have not clicked yet.

**Measure a candidate signal before shipping the tile.** A tile that counts noise is worse than no
tile. Two of Browser's four candidates were dropped on the numbers: *downloads that were opened*
was 53 of 160 (opening what you downloaded is what downloading is for), and *domains only in cache*
was built on `browser_cache.url`, where 273 of 400 sampled rows parse to something that is not a
host. Record the measurement next to the code, or the signal gets "fixed" back in.

**The loading overlay covers re-loads.** The branded first-load screen is a *replacement* gated on
the first payload and can never show again. `<LoadingOverlay>` covers `.dash` only, so the header,
search and date picker stay usable while a filter change runs.

---

## 4. Traps that fail quietly

Each of these looks like success, or like a different problem entirely.

**A slot that runs on the GUI thread freezes the whole window, overlay included.** A QWebChannel
slot runs where its QObject lives. Every dashboard did its SQL there, so the window went "Not
Responding" and the loading overlay stopped mid-animation (a timeline day click: 70 s). A bridge
derives from `visualizations/async_bridge.AsyncBridge`; the page's `call()` sends **data getters**
(named `get*`) through `callAsync` and gets the answer on `asyncResult`, on a thread pool. So:
- name every data slot `get*`, and **never** name a slot that creates a widget (`openEventDetailDialog`)
  `get*` - it would run off the GUI thread;
- answers now arrive out of order: an effect that reloads on a click or a filter uses `latest()`
  (bridge.js), so an older answer cannot overwrite the newer view or clear its overlay;
- `@cached_slot(name, db_paths)` under `@pyqtSlot` keeps an answer until a filter or a database
  mtime changes; shared caches are touched under `self._cache_lock`;
- one SQLite connection per call, as before (connections are thread-bound).
Guarded by `visualizations/tests/test_async_bridge.py`.

**A function around the column hides its index.** `date(timestamp) >= date(?)` and
`MIN(date(col))` make SQLite read every row: one SRUM day took 8.9 s on 457k rows. Times are stored as
`YYYY-MM-DD HH:MM:SS`, which sorts as time, so compare the raw text (`timestamp >= date(?) AND
timestamp < date(?, '+1 day')`) and take `date(MIN(col))`. Check with `EXPLAIN QUERY PLAN`: it must say
`SEARCH ... USING INDEX`, not `SCAN`.

**A capped column flexbox crushes its rows instead of scrolling.** `.res-list` is
`display: flex; flex-direction: column; max-height: 300px`. Its rows are flex children, so they
shrink to fit — and a row whose own `overflow` is hidden (set for the ellipsis) has an automatic
minimum size of **zero**, so nothing stops it. Measured: 40 resource rows rendered at **8px tall
for an 11.5px font**, clipping every glyph into debris. And because the shrink absorbed the
overflow, `overflow: auto` computed nothing to scroll, so no scrollbar appeared either — which is
why it read as *collapsed*. `.evt-row` and `.hour-row` escaped only by accident: they put
`overflow: hidden` on their inner spans, not the row. Guard: `.x > * { flex-shrink: 0 }`.

**A detail modal inside a section that returns early never mounts.** `DaySection` and
`WindowSection` short-circuit when nothing is selected, so opening a record from an insight set the
state, closed the panel, and showed nothing at all. Invisible in normal use, because a day is
usually already selected by the time anyone clicks around. Modals belong in `App`.

**`SELECT COUNT(*)` discards the records**, so an insight can state a number it cannot back up.
Select the rows and count them — the same work for SQLite, and the difference between a figure and
a lead.

**A table's columns vary between parser versions.** Naming a column that is absent fails the whole
query and returns nothing — a non-zero count with an empty list, which reads as *records withheld*.
Ask `PRAGMA table_info` first; `mftusn_bridge._deleted_entry_subjects` is the pattern. (The real
case's `deleted_entries` has nine columns; the test fixture's has three.)

**A name can lie.** `deleted_entries` in `USN_journal.db` holds **gaps in the journal**, not deleted
files — no MFT record number, so those subjects cannot open a file modal and must not pretend to.

**An unreachable spinner looks like a working one.** `{tlLoading && !timeline && <spinner/>}` can
never render if the component already returned a full-screen loader on `!timeline`. Check that the
condition is reachable from where it sits.

**A `.catch()` that substitutes empty data makes a failure look like an empty case.** Record the
error and show it; "that query failed" and "this case has no data" are different claims and only
one of them is the analyst's problem.

**A handler per cell makes a long strip unusable, and it reads as a slow machine.** Shell Items is
4,568 days × 7 sources ≈ **32,000 cells**, and `onMouseMove → setTip` on each of them re-rendered
every one on every mouse move. The cells carry `data-day` and the *row* carries one delegated
handler; the rows are wrapped in `useMemo` whose dependencies exclude the tooltip state. Measured
after: hover on the 32,000-cell strip costs the same as on the 1,130-cell one, with zero long
tasks.

**`repeat(n, 1fr)` is `repeat(n, minmax(auto, 1fr))`.** The widest cell's *minimum* becomes every
track's minimum — and `.usn-cell.sel` has 2px borders, so one selected day gave all 226 of
Browser's tracks a 4px floor and pushed the strip 135px past its pane, making it scroll for no
reason. Always `minmax(0, 1fr)`.

**Two grids that must line up need the same `gap`.** `.usn-axlabels` had none while `.usn-cells`
had one. With `1fr` tracks both filled the pane and it was invisible; with fixed 4px tracks the axis
ended 4,567 gaps short of the cells and every label sat on the wrong day.

**A scroll position set before layout settles goes stale.** When the strip scrolled,
`el.scrollLeft = el.scrollWidth` was clamped to the maximum *at that moment*, measured before the
page's own vertical scrollbar appeared — leaving the most recent day just off the right edge. One
reason the strip is now windowed instead: there is no scroll position to get wrong.

**Every key in a dashboard's colour list needs its ramp.** A strip reads one colour ramp per series;
a series added to the list (`SOURCES`) without its `*_RAMPS` entry throws during render and blanks
the whole dashboard with no visible error.

---

## 5. Never render a secret

A raw dump of a browser row would put encrypted passwords, cookie values and saved-card fragments
on screen and into reports. `raw_record.py` withholds by exact name and by suffix
(`*_encrypted_b64`, `*_token`, …), and new parser columns are caught by the suffix rule without
anyone remembering.

A withheld column is **named, not dropped**. That a row *has* a stored password is a finding; the
password is not.

---

## 6. Verify what reached the screen

Structural checks say nothing about how a dashboard looks. A heat map can be non-empty and
unreadable; a list can be present and crushed to 8px.

- Drive the real bridge through the render harness (`scratchpad/viz_harness.py` + headless Chrome
  over CDP), then **read the PNG**.
- The harness redacts evidence to **same-length** placeholders, so layout, wrapping and overflow
  behave exactly as with the real strings while no path, host or file name reaches an image.
  Redact by field name **and** by value — it once redacted only `name`, and a screenshot of the
  Full record section carried real values.
- Interaction needs driving, not rendering: a static shot cannot show that an overlay appears on a
  reload and clears afterwards. `scratchpad/chain.js` and `reload.js` are the models.
- **Prove a new guard fails** before trusting it. In one session that caught six tests that could
  not fail — two dead regexes, a gap masked by a dead CSS rule, a check an import line satisfied,
  one asserting a column the table does not have, and one matching its own documentation.

Run `pytest visualizations/tests/`. Then `diff -q` every touched file **and every rebuilt
`dist/index.html`** against the EXE tree.
