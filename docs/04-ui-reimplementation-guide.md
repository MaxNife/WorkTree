# WorkTree console: UI reimplementation guide

Written 2026-11-11. This is the build guide for a full redesign of the console: what each screen is
for, how it is laid out, what every action does, and how it should feel.

**The theme is a garden: plants, nature, vibrant and colourful, on a clean light base.** The owner
reviewed a mockup sheet (`mockups/redesign-options.html`) on 2026-11-11 and approved its palette,
the Bloom logo, solid flower shapes for workflow nodes, a colour band per area with coloured cards,
and the device's own fonts. This guide is written to that sheet. It replaces the earlier
green-and-brown design language (`docs/design-language.md`) completely; nothing from that look is
carried over except what is stated here.

What survives from the earlier work, because it was right: native HTML controls with our own
components and no UI kit; Phosphor icons; a status always shown with its word; the plant idea on
the canvas ("shape says what a node does, colour says its family"); dense tables; full keyboard
operation. The earlier board is kept for reference in `design-source/canvas-design/`.

How app connectors and skill nodes look and behave is in `07-nodes-and-connectors.md`.

## 1. Where the console is today, and what "ten times better" means

**Today.** The shell, sign-in and Operations are built and tidy. Inbox, Studio, Data and Admin
each show one sentence. Home redirects to Operations. Run now asks for raw JSON. Screens poll while
a run is active because the server sends no start events. There is no canvas, so the product's
reason to exist cannot be used from the browser.

**The bar.** Ten times better is not more decoration. It is these seven measurable things:

| # | Promise | Measure |
|---|---|---|
| 1 | Complete | Every job in the product can be done in the console: build, test, publish, promote, run, decide, administer |
| 2 | Instant | Any click answers in under 100 ms. Navigation between visited screens shows content in under 200 ms. No full-page spinner, ever |
| 3 | Live | What is on screen is true now. A step that starts appears within one second without a refresh |
| 4 | Keyboard-complete | Every action has a key path. An operator can clear ten tasks without touching the mouse |
| 5 | Forgiving | Anything reversible is undone with one key instead of confirmed with a dialog. Nothing typed is ever lost |
| 6 | Explains itself | Every error says what happened, why, and what to do next, at the place it happened |
| 7 | Unmistakably WorkTree | A screenshot of any screen, with the logo cropped out, is recognisable as this product: flower colours, plant shapes, a light clean ground |

## 2. How it should feel

Three words: **bright, quick, alive.**

- **Bright.** Seven flower colours of equal strength on a light, faintly violet ground. Every area
  has its own colour and every workflow its own flower. Colour is how a person knows where they are
  and what they are looking at. It is generous, but it is organised: a colour always means
  something.
- **Quick.** Things respond before the server does. Motion is short and always has a cause. A
  person who knows the keys never waits for the pointer.
- **Alive.** A running workflow looks like something growing: petals fill, stems thicken as rows
  pass, a router opens from bud to bloom when data reaches it. Runs are "growing", not "running".
  Small moments of delight are allowed (a flower that opens when a run finishes clean) as long as
  they never delay anyone.

The balance that makes it work: **colour on the frame, clarity in the content.** Bands, navigation,
cards, flowers, status and charts are colourful. Tables, forms and long text sit on white with dark
ink so they can be read all day.

A useful test for any screen: *would a tired operator at 06:10 understand it in two seconds, and
does it look like a garden rather than a filing cabinet?*

## 3. Foundations

### 3.1 Colour

`web/src/theme/tokens.ts` stays the single source, but its contents are replaced.

**The seven flowers** (each has a strong value, a soft tint for fills, and a deep value for text on
the tint):

| Name | Strong | Soft | Deep (text on soft) | Text on strong |
|---|---|---|---|---|
| Hibiscus | `#EE3F3A` | `#FFE7E3` | `#B3211D` | white |
| Marigold | `#FFB01F` | `#FFF1CF` | `#7A4E00` | Night soil |
| Fern | `#0E9F5B` | `#DDF6E6` | `#0A6B3D` | white |
| Lagoon | `#0AA5B8` | `#D9F4F7` | `#06707D` | white |
| Morning glory | `#2A7BEA` | `#DFEBFE` | `#1553B0` | white |
| Iris | `#6246EA` | `#E8E3FF` | `#3A2A9E` | white |
| Orchid | `#E0288F` | `#FFE1F1` | `#9C1561` | white |

**Neutrals** (faintly violet, never brown or grey-beige):

| Token | Light | Use |
|---|---|---|
| `--wt-ground` | `#FBFAFE` | The page |
| `--wt-surface` | `#FFFFFF` | Cards, tables, panels |
| `--wt-sunken` | `#F4F1FA` | Selected navigation, table header, segmented controls |
| `--wt-line` | `#E7E2F0` | Hairlines |
| `--wt-line-strong` | `#CFC8DC` | Field edges |
| `--wt-ink` (Night soil) | `#231F2E` | Text, the strongest buttons |
| `--wt-muted` | `#5E5670` | Secondary text |

**What each colour is for.** Colour is plentiful but never arbitrary:

| Job | Rule |
|---|---|
| **Area** | Home marigold, Operations hibiscus, Inbox orchid, Studio iris, Data lagoon, Connections morning glory, Insights fern, Admin Night soil. The area colour paints the navigation leaf, the band at the top of the area's pages, and the area's empty states |
| **Workflow** | Every workflow has a flower: one of the seven colours and a petal count from 5 to 9, chosen at creation (changeable). The flower appears beside the workflow's name everywhere: lists, runs, tasks, charts, the canvas title |
| **App** | Every app connector has a fixed colour (see `07-nodes-and-connectors.md`). It colours the node on the canvas |
| **Status** | Fern done, hibiscus failed, morning glory growing (running), marigold waiting, muted for cancelled and queued. Always a pill with a dot **and the word** |
| **Action** | Iris for the main button of a view. Night soil for the single strongest action on a coloured band. Hibiscus for destructive actions |
| **Focus** | A 2 px Night soil ring with a 2 px white gap, on every focusable thing |

Text on a strong colour is white, except Marigold, which takes Night soil. White on Fern, Lagoon
and Morning glory is for bold text and icons only (they do not reach 4.5 to 1 for small text);
body-size text on colour always uses the soft tint with its deep value. Contrast is unit-tested for
every pair in the table.

**Dark theme.** Ground `#17141F`, surface `#211D2B`, sunken `#131019`, line `#35304A`, ink
`#F5F2FB`. The seven strong colours stay the same; the soft tints become 18 percent of the strong
colour over the surface, and the deep values become lighter tints (for example Hibiscus text
`#FF9C96`). **High contrast** drops the tints, keeps the seven colours only where they pass on
black, and uses the one-colour logo.

### 3.2 Type

The device's own interface font, with no web font loaded (the owner's decision; it also suits an
on-premise install):

```
--wt-font:      'Segoe UI Variable Text', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'SF Pro Text',
                Roboto, 'Helvetica Neue', Arial, sans-serif;
--wt-font-head: 'Segoe UI Variable Display', 'Segoe UI', -apple-system, BlinkMacSystemFont,
                'SF Pro Display', Roboto, 'Helvetica Neue', Arial, sans-serif;
--wt-font-mono: 'Cascadia Mono', Consolas, 'SF Mono', Menlo, 'Roboto Mono', monospace;
```

Character comes from weight and size, not from a special typeface: headings are heavy (700) and
slightly tight (-0.02em), numbers on the Home tiles are large and bold. Six steps, each with a job:

| Step | Size / line | Weight | Use |
|---|---|---|---|
| Display | 30 / 34 | 700 | Home greeting, big numbers, empty Studio |
| Title | 24 / 30 | 700 | Page titles on the area band |
| Heading | 16 / 22 | 700 | Card and panel headings |
| Body | 14 / 20 | 400 | Everything by default |
| Small | 12 / 16 | 400 | Meta, table secondary text, hints |
| Micro | 11 / 14 | 500, +0.02em | Column headers, chips, key hints |

Numbers in tables and durations use tabular figures (`font-variant-numeric: tabular-nums`) so
columns do not jitter while values change. Ids, paths and code use the mono stack.

### 3.3 Space, shape, depth

- Spacing scale 2, 4, 6, 8, 12, 16, 20, 24, 32, 48. Page gutter 24 (comfortable) or 16 (compact).
- **Soft, generous corners.** Radius 10 for controls, 16 for cards and tables, 20 for the app frame
  and dialogs, full for pills.
- **The leaf.** One corner shape belongs to WorkTree: a leaf, made with
  `border-radius: 3px 60% 3px 60%`. It is the navigation marker for each area and the marker beside
  a task or list item. A gentler version (`16px 16px 16px 4px`) is used for the stat tiles and
  colour swatches, so coloured blocks look planted rather than boxed.
- **Plant shapes are drawn, not imported.** Flowers, petals, seeds, buds and leaves are generated
  from four small functions (`flower`, `petal`, `seed`, `bud`) shared by the logo, the workflow
  avatars, the canvas nodes and the decorations. One source keeps every plant in the product in the
  same hand.
- **Decoration** is allowed in three places only: the area band (one or two flowers at its right
  end, in the area's colour and one neighbour), empty states (a small plant in the area's colour),
  and the sign-in page. Never behind text, never in tables or forms.
- Flat on the page; one soft violet-tinted shadow for what floats
  (`0 2px 4px rgba(35,31,46,.06), 0 10px 28px rgba(35,31,46,.12)`). Three layers only: page, raised
  (popover, panel), overlay (dialog, palette).
- Row height 34 compact, 42 comfortable. Control height 30 and 34.

### 3.4 Motion

Motion explains cause and effect. It is never a wait.

| Token | Value | Use |
|---|---|---|
| `--motion-instant` | 80 ms, ease-out | Hover, press, focus |
| `--motion-quick` | 140 ms, ease-out | Menus, popovers, tooltips, row expand |
| `--motion-move` | 220 ms, cubic-bezier(0.2, 0, 0, 1) | Panels sliding, items reordering, canvas pans made by the system |
| `--motion-grow` | 420 ms, cubic-bezier(0.3, 0, 0.1, 1) | Plants only: petals filling, a bud opening, a stem thickening, a flower opening when a run finishes |

Rules: things enter from where they came from and leave the way they came. A new row fades in with
a 600 ms tint that then fades (so the eye finds it) and never shifts the row under the pointer:
new rows queue behind a "3 new runs" chip when the user has scrolled or is hovering. Nothing loops
except the filling petals of a step that is running. `prefers-reduced-motion` turns every transition into a cross-fade under
80 ms; petals still fill to show progress, but nothing sways, travels or opens.

### 3.5 Density and themes

Kept: compact by default, comfortable toggle, follow the system theme with manual override, all
remembered per user (move from `localStorage` to the user's server-side preferences so they follow
the person).

## 4. Interaction grammar

These rules hold on every screen. Build them once in the shared layer.

### 4.1 Response and loading

- **Optimistic first.** Claim, complete, pause, rename, tag, star, reorder: the screen changes at
  once, the request follows. If it fails, the change rolls back and a toast says why, with Retry.
- **Skeletons, not spinners.** First load of a region shows a skeleton in the shape of the content
  for at most the time it takes; a region that already has data never blanks, it shows the old data
  with a thin progress line at its top edge.
- **Prefetch on intent.** Hovering or focusing a row for 80 ms prefetches its detail. Detail pages
  therefore open with content.
- **Keep place.** Back restores scroll position, selection, open rows and filters. Filters, sort,
  tab and selection live in the URL so any view can be shared as a link.

### 4.2 Undo over confirm

| Kind of action | Pattern |
|---|---|
| Reversible (archive, disable a trigger, unclaim, remove a tag, delete a node) | Do it. Toast: "Trigger paused. Undo" for 8 s. `Ctrl+Z` also undoes it |
| Costly but reversible (cancel a run, reassign a task) | A small popover at the button: one sentence and one confirm button. No modal |
| Irreversible or governed (publish, approve a promotion, deactivate a user, rotate a secret, delete a workflow) | A dialog that names the object and the consequence. Destructive ones require typing the name |

### 4.3 Errors

- At the field for input errors, with the message under it and focus moved to the first one.
- At the object for action errors (a bar inside the card or panel that failed).
- At the page only when the page cannot load, with Retry and the correlation id in small text,
  click to copy.
- Every message has three parts: what happened, why, what to do. "The run could not start. A run
  for period 2026-10-31 is already active. Open that run, or wait for it to finish."
- Offline or server unreachable: a slim bar under the top bar, "Reconnecting...", and all mutating
  controls disable. It clears itself.

### 4.4 Keyboard model

One model, shown in a cheat sheet on `?`:

| Keys | Action |
|---|---|
| `Ctrl/Cmd+K` | Command palette |
| `/` | Focus the screen's filter |
| `g` then `h o i s d c n a` | Go to Home, Operations, Inbox, Studio, Data, Connections, Insights, Admin |
| `j` `k` or arrows | Move in a list |
| `Enter`, `o` | Open. `Ctrl+Enter` opens in a side peek |
| `x`, `Shift+x` | Select, extend selection |
| `Esc` | Close the top layer, then clear selection |
| `.` | Open the actions menu for the focused item |
| `?` | Shortcuts for this screen |
| `Ctrl+Z`, `Ctrl+Shift+Z` | Undo, redo |

Single-letter keys are off while a text field has focus. Every shortcut is listed beside its
action in menus and tooltips, so the keys teach themselves.

### 4.5 Selection, peek and bulk

Lists support multi-select. A selection bar rises from the bottom edge with the count and the bulk
actions (retry, cancel, claim, reassign, tag). `Space` on a focused row opens a **peek**: a
right-hand panel with the essentials and the main actions, so a person can walk a list with `j`
and `k` and never lose their place. `Enter` opens the full page.

### 4.6 Live data

- One event stream per tab updates the query cache. A small **live dot** in the top bar shows
  state: steady (connected), hollow (reconnecting), with a tooltip. No "Live updates paused" bar
  unless it has been down for more than 10 s.
- Relative times tick. Durations of running things count up every second.
- A value that changes flashes its background once (the 600 ms tint).

### 4.7 Words

Sentence case everywhere. Buttons are verbs ("Publish", "Approve", "Run now"). No "Submit", "OK"
or "Are you sure?". Empty states say what the thing is and offer the one next action. Dates are
relative under 7 days with the exact time on hover; absolute after. Secrets are never shown: a
value is "set", "not set" or "rotated 12 days ago".

## 5. The shell

```
+--------+------------------------------------------------------------+
| logo   |  Operations / Runs / Invoice reconciliation   (o) [Search Ctrl K] (bell) (avatar)
+--------+------------------------------------------------------------+
| Home   |                                                            |
| Operations  >                                                       |
| Inbox   12 |                        page                            |
| Studio  >  |                                                        |
| Data       |                                                        |
| Connections|                                                        |
| Insights   |                                                        |
| Admin      |                                                        |
|            |                                                        |
| pinned     |                                                        |
| - Bank rec |                                                        |
+--------+------------------------------------------------------------+
```

- **Sidebar.** White, with the Bloom lockup at the top. Eight areas, each marked by a **leaf in the
  area's colour**. The current area sits on the sunken tint with its label in ink. Collapses to
  leaves only (`[`). Inbox shows the count of tasks waiting for me in an orchid pill. Under the
  areas, **Pinned**: workflows and saved views the user pinned, each with its flower. The Studio
  tree of folders loads lazily and remembers what was open. Exact-match highlighting (fixes
  Dashboard and Runs lighting up together).
- **Top bar.** White. Breadcrumbs on the left; each crumb is a menu of its siblings. On the right:
  live dot, search, notifications, user avatar. Height 46.
- **The area band.** Directly under the top bar on every area's main pages: a band in the area's
  soft tint holding the page title (heavy), one sentence of live summary, the page's main action in
  Night soil at the right, and one or two drawn flowers. Tall (about 96 px) on an area's landing
  page, short (about 64 px) on its other pages, absent on dense working screens (the Studio editor,
  a task being worked) where space matters more. The band is how a person always knows which area
  they are in.
- **Environment marker.** When the user is looking at prod data or is about to act in prod, the
  word "prod" appears as a Night soil pill beside the page title and the band gains a 3 px Night
  soil line along its bottom edge. Dev and test show a quiet outlined pill.
- **Command palette.** Opens in 80 ms with recent items. Searches workflows, runs (by id or
  workflow), tasks, people, settings and actions together, grouped, with fuzzy matching. Typing `>`
  limits to actions, `#` to runs, `@` to people. `Enter` runs; `Ctrl+Enter` opens in a peek. Actions
  that need a value (Run now, Reassign to) continue inside the palette as a second step instead of
  navigating away.
- **Notifications.** A popover, not a page: grouped by run or task, newest first, unread dot, "Mark
  all read". Clicking goes to the object. Preferences decide which kinds also email.
- **Feel.** The shell never reloads. Changing area cross-fades the page region in 140 ms while the
  sidebar and top bar stay still.

## 6. Sign-in and system screens

**Sign in.** Two halves. On the left, a white panel with the Bloom lockup and the form. On the
right, a garden: a row of drawn flowers in all seven colours on the page colour, which sway once as
the page loads and then rest. On narrow windows the garden becomes a strip above the form.
Username, password, "Sign in" (iris). When single sign-on is configured, one "Continue with Microsoft" button comes first and
local sign-in sits behind "Use a local account". Errors appear under the form in one line and never
say which field was wrong. After five failures the button shows the wait in seconds. Focus starts
in the first field; `Enter` submits; the redirect returns the user to where they were going.
*Feel: a bright welcome, and then straight to work. The garden is the only illustration of this
size in the product.*

**Session ended.** If the session expires while the user is working, a dialog over the current
screen asks them to sign in again; the page behind keeps its state, and unsaved text is preserved.

**No access, not found.** Title, one sentence, a link back to the last good page and to Home. The
no-access page names the role or folder that is needed.

**Profile and preferences.** Display name, theme, density, start page, time zone, notification
choices, change password, active sessions with "Sign out" beside each, personal API tokens.

## 7. Home

Purpose: answer "what needs me, and is everything fine?" in five seconds. Different for each role
because it is built from what the person may do.

Layout, top to bottom (as on the approved mockup):

1. **Marigold band**: "Good morning, Kemi." (Display) and one sentence of state: "3 tasks are
   waiting for you and one is due in 40 minutes. 2 runs failed overnight." Each number is a link.
   "Run a workflow" in Night soil at the right. Two flowers.
2. **Four tiles**, each a different soft tint with a leaf corner and a large bold number: runs
   today (fern), growing now (morning glory), tasks for you (orchid), hours saved this month
   (iris). Each has one line of context under the number and opens the matching view.
3. **Needs you** (left card, wide): tasks assigned to my roles or me, ordered by due time, with a
   leaf in the colour of their kind and the SLA as a pill; promotion requests I can decide; failed
   runs of workflows I own. Each row acts in place: Claim (iris), Review, Open run.
4. **Growing now** (right card): running workflows, each with its flower, a progress bar in the
   flower's colour and the current step; then the next five scheduled runs with their times.
5. **Recently viewed**: the last six things I opened, as flowers with names.

Empty system (first install): the band says "Plant your first workflow" and the page becomes three
steps, each a card with a seed that turns into a flower when done: add a connection, build a
workflow from a template, run it.

*Feel: walking into a garden in the morning and seeing at a glance what has grown and what needs
water. Colourful, but each colour is telling you something.*

## 8. Operations

### 8.1 Runs

Purpose: find any run and see the state of all of them.

- **Layout.** A short hibiscus band ("Runs", "148 today. 6 growing, 2 failed.", "Run now"), a row
  of view chips, then a white, dense table in a rounded frame: workflow (its flower and name),
  status pill, now at (current step or failure reason), trigger, started, took, requested by.
  Columns can be shown, hidden and reordered; the choice is saved with the view.
- **Views.** Chips: All, Growing, Failed, Waiting, Mine, plus saved views, each with a count. The
  selected chip is Night soil. A saved view keeps filters, sort, columns and density, and can be
  shared.
- **Filter bar.** One field with tokens: typing `status:failed workflow:"Bank rec" env:prod
  since:7d` builds chips. Suggestions appear as you type. `/` focuses it.
- **Live.** New runs arrive at the top with the tint. Growing rows show their
  flower's petals filling and a duration that counts.
- **Actions.** Row: open, peek, retry, cancel, copy id, open workflow. Bulk: retry failed, cancel.
- **Group by** workflow, status or day, with counts in the group headers.
- **Timeline toggle.** Switches the table for a swim-lane view: one lane per workflow, runs as bars
  on a time axis coloured by status. Answers "what was running at 06:15?".
- **Empty.** "No runs match these filters. Clear filters" or, with no runs at all, "Nothing has run
  yet. Run a workflow".

*Feel: a well-kept bed seen from above. Each row is one plant with its flower and its state.
The table itself is white and exact; the colour is in the flowers and the pills.*

### 8.2 Run detail

Purpose: understand one run completely, and act on it.

- **Header.** A band in the **workflow's own colour** (soft tint) with its flower, the workflow
  name, run number, status pill, environment, version, trigger, started, duration (counting),
  requested by. Actions: Cancel (while active), Retry from failed step, Run again with the same
  inputs, Open in Studio.
- **Two ways to look, one toggle** (`v`):
  - **Steps** (default for operators): the vine. One fern-coloured stem down the left, one small
    flower per step in the step's app colour: a closed bud when pending, petals filling while it
    runs, fully open when done, wilted (hibiscus, drooped) when failed. Parallel branches fork the
    stem and rejoin. A step row shows name, activity, duration, attempts
    and a one-line result. Expanding it shows tabs: Output (as a tree with copy-path), Input (masked),
    Logs (streaming, searchable, wrap toggle, "follow" on by default until the user scrolls),
    Attempts, Files. The first failed step opens by itself and the view scrolls to it.
  - **Canvas** (default for authors): the workflow as built, with the run painted on it. Flowers
    open, stems thick where rows flowed, the route taken through each router in full colour and the
    others faded. Clicking a node opens the same step panel on the right. A scrubber along the
    bottom replays the run in time.
- **Side column.** Properties, inputs, a "Waiting on" block when a task is open (who, due when,
  link), artifacts with size and download, sub-runs, the activity feed and comments.
- **Failure.** A bar at the top states the failing step and its message, with "Go to step" and the
  most likely action (Retry, Open the secret's policy, Open the task).
- **Live.** Steps appear as they start. The current step's petals fill. Logs stream. When a run
  finishes clean, its flower in the header opens once (420 ms); when it fails, nothing celebrates.
- **Keys.** `j` `k` between steps, `Enter` expand, `l` logs, `r` retry, `c` cancel, `v` view.

*Feel: like watching the work happen. When it fails, the screen has already taken you to the
problem.*

### 8.3 Run now

A dialog (or the second step of the palette action). Choose the workflow (search, recent first),
environment and version. Below, a **form generated from the workflow's input schema**: dates get a
date picker, enums a select, files an upload into the run workspace. Advanced: edit as JSON. The
duplicate guard is checked while typing: "A run for 2026-10-31 is already active" appears before
the button is pressed, with a link, and the button becomes "Queue behind it" when the workflow
queues. The last inputs used are offered as a starting point. `Ctrl+Enter` runs and opens the run.

### 8.4 Triggers

(Today's Schedules screen, widened to all trigger kinds.)

- A table: name, workflow, kind (schedule, webhook, file, dependency), environment, next fire, last
  fire and its result, enabled switch.
- **Schedule editor.** A plain-language builder ("Every weekday at 06:00") with the cron text
  beside it, both editable and kept in step, a time zone, the calendar rule for holidays, and a
  preview of the next five fire times. Catch-up behaviour is a sentence with a switch.
- **Webhook.** Shows the URL and how to call it, the token once at creation, rotate, expiry, the
  last ten deliveries with status.
- **File.** Folder (picked from allowed roots), pattern, settle time, a test that lists what would
  match now.
- **Calendar view** of the next two weeks, to see collisions.
- Pausing a trigger is a switch with undo. A paused trigger is greyed with the word "Paused".

### 8.5 Workers

One row per worker: host, pools, slots (a row of small buds, filled in the colour of the workflow
each is growing, empty when free), what each slot is running (linked), version, last heartbeat,
state. Actions: Drain, Resume. Above the table, each
pool's queue depth and oldest wait. A pool with work and no ready worker shows a warning sentence at
the top of the page. *Feel: an engine room gauge. One look says whether capacity is fine.*

## 9. Inbox

Purpose: get human decisions made quickly and correctly.

### 9.1 List and detail

- **Layout.** Three columns. Left (narrow): views: Mine, My role, Unclaimed, Overdue, Completed,
  and saved views, each with a count. Middle: the task list. Right: the selected task.
- **List row.** A leaf in the colour of the task kind (approval iris, manual match orchid, data
  entry lagoon, exception hibiscus), title, the workflow's flower, assignee (person or role), and
  the SLA as a pill: muted when comfortable, marigold under 25 percent left, hibiscus when overdue,
  always with the words ("due in 40 min", "2 h overdue").
- **Detail.** Title, status, the context that the workflow passed (a readable summary first, raw
  data behind a toggle), the form for this task type, the reason field, the decision buttons, then
  history and comments. A link to the run opens it as a peek so the task stays on screen.
- **Flow.** `j` `k` move, `c` claims, the form takes focus, `Ctrl+Enter` completes with the primary
  decision, and the next task loads by itself. Completing is optimistic with an 8 s undo.
  Claiming is implicit when a person starts typing in a task nobody holds.
- **Collision.** If someone else claims the task while it is open, the form locks with "Claimed by
  Tunde a moment ago" and a "Request handover" action.

### 9.2 The task forms

| Type | Screen |
|---|---|
| **Approval** | What is being approved in one sentence, the evidence (figures, files, a diff where there is one), two buttons: Approve (primary) and Reject. Reject requires a reason and the button stays disabled until one is typed. Keys `a` and `r` |
| **Data entry** | A form generated from the task's schema, validated as typed, with the source document shown beside it when there is one. `Ctrl+Enter` submits |
| **Exception disposition** | The exception, its history, and three choices: Resolve, Write off, Escalate. Write off and Escalate require a reason; Escalate asks who to |

### 9.3 Board

The same tasks as columns by status (Open, Claimed, Completed today) or by assignee. Cards drag
between people to reassign (with the reason popover). For team leads balancing work.

*Feel: triage. Fast, rhythmic, no dead ends. The reason box is the only place the product slows a
person down on purpose.*

## 10. Studio

### 10.1 Library

A gallery or a table (the view switcher) of workflows in the current folder, under an iris band.
The gallery is a flower bed: each card has a soft tint of the workflow's colour across its top with
the workflow's flower large on it, then the name, owner, a status line
("v12 in prod, draft has changes"), the last run's status and a 14-day sparkline of runs. Folder
tree on the left. Actions: New (blank, from template, import YAML), Duplicate, Move, Archive.
Search covers names, tags, descriptions and activity names ("everything that uses sftp").

### 10.2 Workflow page

Linear-style: editable title and description in the main column, a properties column (owner,
folder, tags, SLA, concurrency rule), then tabs:

- **Overview**: a read-only thumbnail of the canvas, environment strip (which version is in dev,
  test and prod, with "Promote" beside each gap), triggers, recent runs.
- **Runs**, **Versions**, **Triggers**, **Access**, **Activity**.

### 10.3 Editor

The centre of the product. Full-window: the shell's sidebar collapses to icons on entry.

```
+----+----------------------------------------------------+------------------+
| +  |  Invoice reconciliation   Draft, saved 2 s ago     | [Test run] [Publish]
| add|----------------------------------------------------+------------------+
| lib|                                                    |  Node panel      |
|    |                canvas                              |  Input | Setup | Output
|    |                                                    |                  |
|    |                                                    |                  |
+----+--[ - 100% + ] [fit] [tidy] [map]---[Problems 2]----+------------------+
```

**Canvas**

- **Ground.** The page colour with a soft dot grid in pale violet. Pan with drag or two fingers,
  zoom with pinch or `Ctrl+wheel`, `1` fits, `0` is 100 percent. A minimap appears while panning.
- **Nodes.** Solid, simple plant shapes (approved on the mockup sheet). Shape says what a node
  does; colour says which app or family it belongs to:

  | Node | Shape |
  |---|---|
  | Trigger | A **seed**: a teardrop pointing along the flow, with a light eye |
  | App step | A **round-petal flower**, eight petals, in the app's colour, light centre holding the app's glyph |
  | Skill | A **pointed-petal flower** (dahlia), so custom behaviour stands out |
  | Person | A **sunflower**: many thin marigold petals around a dark centre |
  | Router (if, switch) | An **open bloom**: one long petal per route, each in the colour of the node it leads to, dark centre |
  | Parallel and merge | Petals fanning out; petals folding in |
  | Loop | A flower with a small curled tendril, around a group |
  | Wait | A **closed bud**, dashed outline |
  | Sub-workflow | A **cluster** of three overlapping blooms |
  | Finish | A **leaf** |
  | Stop with failure | A wilted, drooping hibiscus flower |
  | Note | A pale leaf with text |

  The label and one line of summary sit under the node ("Read rows, *Invoices* sheet"), written by
  the node from its settings.
- **Stems.** Connections are stems: smooth curves that take the colour of the node at each end and
  blend between them. Thickness follows volume (hairline for a record, thicker with row count for a
  table). Counts ride on the stem ("1,204 rows"). Small leaves grow on long stems. A failure path is
  a thin dotted hibiscus stem.
- **States.** Pending: the flower is a pale outline. Growing: petals fill clockwise in full
  colour. Done: fully coloured, with a brief open-up. Failed: wilted, with a hibiscus dot. Waiting:
  a dashed halo in the node's colour. Selected: a dotted ring in the node's colour around it.
- **Adding.** Three ways, all fast: drag from the library rail; press the bud on any branch to
  insert between two nodes; or press `Tab` with a node selected to open the add menu at the pointer,
  type a few letters and press `Enter`. The new node arrives already connected and already selected
  with its panel open.
- **Connecting.** Drag from a port. Valid targets glow softly, invalid ones dim. Dropping on empty
  canvas opens the add menu so a connection always ends somewhere. Ports are named on hover
  (`done`, `failed`, `true`, `approve`).
- **Selecting and editing.** Click, shift-click, marquee. Copy, cut, paste, duplicate (`Ctrl+D`),
  delete, all with undo. Selected nodes move with arrows (`Shift` for larger steps). `Ctrl+G` groups
  into a grove; "Extract to sub-workflow" turns a selection into a new workflow and replaces it with
  one node.
- **Tidy** (`Ctrl+Shift+L`) lays the graph out left to right with animated moves so the eye can
  follow.
- **Notes.** Leaf notes anywhere on the canvas, markdown, for the next author.
- **Problems.** Validation runs as you edit. A node with an issue wears a small alert mark; the
  Problems drawer lists all of them; clicking one selects the node and focuses the field.

**Node panel** (right, resizable, three tabs, also openable as a wide overlay with `Enter` to show
all three side by side as in the locked design)

- **Input.** What reaches this node: the outputs of upstream nodes as a tree. With a past run
  pinned, real values; otherwise the typed shape from the activities' output models. Any field can
  be dragged into a setup field.
- **Setup.** A form generated from the activity's schema. Operation first, and only the fields
  that operation uses. Each field is plain by default; a small "fx" turns it into an expression
  field with a chip for each reference (`match > unmatched_left`) and a live preview of the resolved
  value underneath. Credential fields are a secret picker that lists only secrets allowed for this
  activity, host and environment, and say why another is not offered. Below the inputs, a
  collapsed **Behaviour** section: retries, timeout, on failure, persist, pool, notes.
- **Output.** The result of the last test of this node, or the pinned run's output, as a tree and
  as a table when it is tabular, with copy-path on every key.
- **Run this step.** A button at the top of the panel. It runs the node alone with pinned upstream
  data and shows the result in Output with its duration and logs. *Feel: a REPL for one step.
  Change a field, press `Ctrl+Enter`, see the result.*

**Test run.** Runs the draft in dev. The canvas does not navigate away: it comes alive in place.
Petals fill, small seeds travel along the active stem, routers open from bud to bloom, counts
appear on stems. A slim
strip at the bottom shows the run's status with Stop and "Open run". When it ends, every node keeps
its result until the next edit, so the author can click through what happened.

**Saving.** Autosave to the draft 800 ms after the last change. The header says "Saved" with a
time, or "Saving...", or "Offline, changes kept here". There is no Save button. Undo history
survives a reload. If someone else has changed the draft, a bar offers to view their changes, take
theirs, or keep mine, with a diff.

**Publish.** A dialog: the version number it will get, a required one-line change note, a summary
of what changed (nodes added, removed, changed) and any warnings. Publishing is one key from the
dialog. Afterwards the header offers "Request promotion to test".

**YAML view** (`Ctrl+Shift+Y`). A side-by-side editor with schema completion and inline
validation. Edits on either side update the other. For people who prefer text and for code review.

**Step list view.** The same workflow as an outline for keyboard and screen-reader users: every
node is a row, branches are nested, all editing works. This is the accessible equivalent of the
canvas, not a fallback.

The node panel, the add menu, connections and the setup screens for app and skill nodes are
specified in `07-nodes-and-connectors.md`, section 8.

*Feel: the canvas is the garden itself. Movement is soft and organic (`--motion-grow`), things
settle rather than snap, and a successful test run should feel like watching a bed come into
flower. The panel beside it is white, plain and exact, so the settings are easy to get right.*

### 10.4 Versions, compare, promote

- **Versions.** A list: number, note, author, date, where it is deployed. Selecting two opens
  **compare**: the two canvases side by side with added nodes outlined in the add colour, removed in
  the remove colour, changed with a dot; clicking a changed node shows a field-level diff. A text
  diff of the YAML is one toggle away.
- **Promote.** A request shows what the approver needs: the diff against what is in the target
  environment now, the secrets the version uses and their allowed hosts, the test runs of this
  version and their results, the author and the requester. Approve and Reject, reason required for
  Reject. The buttons are disabled with an explanation when segregation of duties forbids the viewer
  ("You wrote this version, so someone else must approve it").
- **Environment strip.** Three stops (dev, test, prod) on one stem: a seed, a bud and an open
  flower in the workflow's colour, with the version at each. The gap between two stops carries the
  Promote action.

### 10.5 Templates

A gallery of starter workflows (portal download to report, file arrival to database load,
approval chain). Choosing one opens a short form for its variables and creates a draft.

## 11. Data

- **Views.** Any collection (runs, tasks, workflows, artifacts) as a table, board or gallery with
  filters, sort, grouping and saved views that are personal or shared. One switcher, the same
  everywhere it appears.
- **Files.** Artifacts across runs: name, type, size, run, step, created, retained until. Preview
  for CSV, Excel (first sheet, first rows), PDF, images and text in a peek. Download. Search by name
  and by run. Checksums shown and copyable.

## 12. Connections

Purpose: manage credentials without ever seeing them. The full design, built around typed
**connections** rather than loose secrets, is in `07-nodes-and-connectors.md` section 8.7. In short:

- **List.** Name, description, where it is used (count of workflows), environments, allowed hosts,
  last rotated, last used, health (a "not used in 90 days" or "rotation overdue" note).
- **Detail.** Policy editor: environments as three switches, allowed hosts as a token field with
  validation and a "test this URL" check, allowed folders. Usage: the workflows and nodes that
  reference it and the last twenty uses with host and run. History: every rotation and policy change
  from the audit log.
- **Create and rotate.** The value is typed once into a field that never echoes it back, with a
  "paste" affordance and a strength note for passwords. After saving, the value cannot be read by
  anyone, and the screen says so.
- A secret that cannot be used where an author tried to use it explains itself in the Studio and
  links here.

*Feel: a greenhouse with a lock on the door. Bright and orderly, and deliberate about who gets in.*

## 13. Insights

Four questions, one section each, each with a date range and a workflow filter:

1. **Is it working?** Success rate over time, failures by workflow and by reason.
2. **Is it fast enough?** Duration percentiles, SLA met or missed, queue wait.
3. **Where do people wait?** Task time to claim and to complete by type and role, overdue trend.
4. **What is it worth?** Hours saved (successful runs times each workflow's manual minutes), runs
   by trigger.

Charts are colourful and clear: each workflow is drawn in its own flower colour with its flower as
the series marker, direct labels instead of legends where they fit, rounded bar ends, soft tinted
area fills under lines, tabular data one toggle away, every chart downloadable as CSV. Status
charts use the status colours only.

## 14. Admin

| Screen | Content and behaviour |
|---|---|
| **Users** | Table: name, username, roles, last sign-in, status, sign-in method. Invite or create; set roles with checkboxes and a sentence describing what each allows; reset password; deactivate (typed confirmation; shows what they own that will need a new owner). The last Admin cannot be removed and the control says why |
| **Roles and access** | The permission matrix, readable. Folder grants: who can view, operate and author in each folder |
| **Environments and promotions** | The three environments; the queue of promotion requests with age; history |
| **Audit log** | A dense, filterable log: time, actor, action, object, source address. Row expand shows before and after as a diff. Filter tokens like the Runs screen. "Verify integrity" runs the chain check and reports the row count, the time, and the last anchor. Export a signed range |
| **Activity packages** | Installed packages, version, signer, activities, which workflows use them. Upload, verify, enable, disable |
| **Access reviews** | A periodic checklist: each user and their roles and grants, with Keep or Remove and a sign-off that is itself audited |
| **Settings** | Read-only view of the effective configuration (no secrets), with the source of each value |

*Feel: the tool shed. The quietest area: a Night soil band, white tables, colour only in status
and in people's avatars. Every change is stated before it is made.*

## 15. What is decided and what is still open

**Decided by the owner on 2026-11-11** (from the mockup sheet):

| Decision | Choice |
|---|---|
| Theme | Plant, nature, vibrant and colourful. Not green and brown |
| Base | Vivid colour on a light base |
| Palette | The seven flowers and Night soil, as in section 3.1 |
| Logo | The Bloom (option A) |
| Workflow nodes | Plant shapes kept, restyled as solid flower forms |
| Colour reach | A colour band per area plus coloured cards and tiles |
| Fonts | The device's own fonts. No web font |

**Still open** (proposed in this guide, not yet seen by the owner):

| # | Proposal |
|---|---|
| 1 | The dark theme values in section 3.1 |
| 2 | Pointed petals for skill nodes, to tell them from app nodes |
| 3 | Each workflow choosing its own flower colour and petal count |
| 4 | The words "growing" for running and "Night soil" and the flower names in the interface |
| 5 | Undo in place of most confirmation dialogs |
| 6 | The token filter field in place of separate filter controls |
| 7 | The step list view as the accessible equal of the canvas |
| 8 | Preferences stored on the server so they follow the person |

## 16. Accessibility

- WCAG 2.2 AA in all three themes, checked by automated contrast tests (kept) and a manual pass per
  release.
- Everything works by keyboard, including the canvas (arrow keys move between connected nodes,
  `Enter` opens the panel, `Tab` adds, `c` starts a connection that arrows then target).
- Live regions announce status changes for the object in focus only ("Step match finished, done"),
  never the whole stream.
- Focus is always visible (the Night soil ring), is moved on purpose after every action, and returns
  to its origin when a layer closes.
- Targets are at least 24 by 24 px; 32 in comfortable density.
- Reduced motion and high contrast are first-class themes, tested.

## 17. Performance budgets

| Item | Budget |
|---|---|
| Initial script, gzipped | 180 kB for the shell; each area loads by itself; the canvas chunk under 250 kB |
| First content after sign-in | 1 s on the office network |
| Interaction to next paint | under 100 ms at p95 |
| Tables | Virtualised above 100 rows; 10,000 rows scroll at 60 frames a second |
| Canvas | 300 nodes pan and zoom at 60 frames a second; edges drawn on one SVG layer; node detail reduces below 50 percent zoom |
| Live updates | Batched to one render per animation frame |

## 18. How to build it

**First, the reskin.** Replace the contents of `web/src/theme/tokens.ts` and `families.ts` with the
palette in section 3.1, rename the CSS variables to `--wt-*`, restyle the existing `U*` components
(radius, field edges, iris primary, pills for status), add the plant drawing functions
(`web/src/plants/`), the `AreaBand`, the leaf marker and the `WorkflowFlower` avatar, and swap the
logo. The built Operations screens then take the new look with small changes, which proves the
system before new screens are built.

**Shared pieces to add** (to the existing `U*` set): `AreaBand`, `WorkflowFlower`, `LeafMark`,
`StatTile`, `StatusPill`, `UMenu`, `UPopover`, `UTooltip`, `UCombobox`,
`UTokenField`, `UDatePicker`, `UToastUndo`, `USkeleton`, `UPeek`, `UTree`, `USplit`,
`UProgressArc`, `UAvatarRing`, `UDiff`, `UJsonTree`, `ULogViewer`, `UForm` (schema-driven),
`UExpressionField`, `USecretPicker`, `UChart`, and a virtualised `DataTable`.

**Canvas kit** (`web/src/studio/`): `graph.ts` (definition to graph and back, pure), `layout.ts`,
`history.ts` (undo), `validate.ts`, `nodes/` (one component per node kind), `edges/`, `panel/`,
`run-overlay.ts`.

**Order.** Follow phase 6 of the upgrade guide: foundations and Home, Inbox, Admin and
Connections, Operations upgrade, Studio pages, Studio editor, Data and Insights.

**Definition of done for a screen**

1. Every state designed and built: loading, empty, partial, error, no access, offline.
2. Keyboard path for every action, listed in the `?` sheet.
3. Light, dark, high contrast; compact and comfortable; reduced motion.
4. Component tests for logic, one Playwright journey for the main path.
5. Live updates verified with two browsers side by side.
6. Reviewed against section 2: bright, quick, alive, with colour on the frame and clarity in the
   content.
