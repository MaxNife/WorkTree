# Nodes and connectors: system design and UI design

Written 2026-11-11. This is the design for everything an author can drop on the canvas: app
connectors (Spreadsheet, PDF, Database and the rest), custom skill nodes (Match, One-time code and
others), and the flow and data tools. It covers how they are built, how data moves between them, and
how each one looks and behaves in the Studio.

It extends `02-system-design.md` (sections 4, 7 and 12) and `04-ui-reimplementation-guide.md`
(section 10). The comparison of Make, n8n and Power Automate that prompted it is in
`Make.com, n8n, and Power Automate Modules Reference Guide.md`.

## 1. What was learned from the three platforms

Sources read: the reference guide, the three directories it links to, and one real connector from
each (Microsoft's Excel Online connector reference, Make's Microsoft Excel app page, n8n's Extract
From File node). The directory pages themselves are only indexes; the detail came from the
individual pages.

| Lesson | Seen in | What WorkTree takes |
|---|---|---|
| One node per app, many operations inside it | All three. Make's Excel app has 22 modules (3 triggers, 13 actions, 6 searches). Microsoft's has 16 actions | **One Spreadsheet node, not twenty.** The author picks the app, then the operation |
| Operations fall into a few kinds | Make: trigger, action, search, plus iterators and aggregators | Every operation declares a kind: `read`, `find`, `write`, `change`, `watch`, `convert`. The kind drives the icon, the retry rule and the safety checks |
| A connection is separate from the node | Power Automate connections, n8n credentials, Make connections | **Connections** are first-class: created once, tested, governed, picked from a list |
| Fields depend on earlier fields | Microsoft: Location, then Document Library, then File, then Table, each a drop-down filled from the one before | **Cascading pickers** filled by live calls at design time |
| Outputs must be known before running | Microsoft publishes a Returns schema per action; "dynamic" where it depends on the file | Every operation has a typed output. Where it depends on the data (a sheet's columns), the node fetches the shape at design time |
| Limits and known issues are part of the contract | Microsoft lists throttling (100 calls per 60 s), a 25 MB file cap, and behaviours per action | Each connector declares limits and the engine enforces them (rate limit per connection, size caps) and shows them in the panel |
| Big data needs a different shape | n8n passes arrays of JSON items; Make passes bundles; both strain on large files. Microsoft returns 256 rows unless paging is turned on | WorkTree passes **tables by reference**. A million rows never travel through the engine |
| Error routes are designed, not accidental | Make's error directives, n8n's continue-on-fail, Power Automate's run-after | Named outcome ports per node, a per-node "on failure" rule, and a workflow-level error path |
| Deprecation happens | Microsoft keeps "Add a row [DEPRECATED]" beside its replacement | Operations are versioned. Old versions keep running and are marked in the Studio with a one-click upgrade |
| Tiers decide who may use what | Standard, premium and custom connectors; verified and community apps | Three trust levels: **built-in**, **organisation** (signed by the organisation) and **restricted** (runs code; Admin only) |

What WorkTree deliberately does differently: no per-operation pricing, no cloud dependency, no
community marketplace, and **skill nodes**: purpose-built nodes for one business behaviour, which
none of the three offer as a first-class idea.

## 2. The four kinds of node

| Kind | What it is | Examples | Shape on the canvas |
|---|---|---|---|
| **Trigger** | Starts a run | Schedule, Webhook, File arrived, After another workflow, Watch (from a connector) | Seed |
| **App** | A connector to one tool or system, with many operations | Spreadsheet, PDF, Database, Files, Email, Web request, SFTP, Browser, Word, Archive | Round-petal flower in the app's colour |
| **Skill** | One business behaviour, designed end to end, with its own setup screen and result view | Match, One-time code, Portal sign-in, Validate, Compare, Approval, Manual match | Pointed-petal flower (a dahlia), so custom behaviour is recognisable at a glance |
| **Flow and data** | Logic that the engine runs itself | If, Switch, Parallel, Merge, Loop, Wait, Set values, Stop; Filter rows, Sort, Join, Group, Pick columns | Router is an open bloom; wait is a bud; data tools are small leaves on the stem |

The rule for choosing between an app operation and a skill: **an app operation does one thing to
one system. A skill encodes a decision or a procedure the business cares about.** "Read rows from a
sheet" is an operation. "Match the bank file to the ledger within tolerance and tell me what is
left" is a skill.

## 3. How data flows

### 3.1 Four value types

Every port on every node carries one of four types. This is the main difference from Make's bundles
and n8n's items, and it is what lets WorkTree handle very large files.

| Type | What it is | How it travels | Shown on the stem as |
|---|---|---|---|
| **Record** | A small JSON object: a result, a summary, a row | In the database, inline (64 kB limit as today) | Nothing, or a field count |
| **List** | Up to 1,000 records, for looping | Inline | "24 items" |
| **Table** | Rows and typed columns | **By reference**: a Parquet file in the run workspace plus a handle | "1,204 rows" |
| **File** | Any file | **By reference**: a path plus a handle | "1 file", or the file name |

A **table handle** is a small record:

```json
{"kind": "table", "path": "tables/invoices.parquet", "rows": 1204,
 "columns": [{"name": "invoice_id", "type": "text"}, {"name": "amount", "type": "decimal(18,2)"},
             {"name": "posted_at", "type": "date"}],
 "sample": "tables/invoices.sample.json", "sha256": "..."}
```

A **file handle** is `{"kind": "file", "path", "name", "media_type", "bytes", "sha256"}`.

Because the handle carries the columns, every node downstream knows the shape of the data before
anything runs. That is what makes column pickers, mapping and validation possible at design time.

Column types are fixed: `text`, `integer`, `decimal(p,s)`, `number`, `date`, `datetime`, `boolean`.
Money is always `decimal`, never a float. Every connector converts to and from these.

### 3.2 Loops are explicit, and rarely needed

Make and n8n loop over items implicitly, which surprises people. In WorkTree:

- A node that receives a **Table** processes the whole table in one execution. No loop.
- A node that receives a **List** runs once. To run a node per item, the author adds a **Loop**
  node, and the canvas shows the loop body as a group.
- **Table to List** and **List to Table** are explicit data tools (Make's iterator and aggregator),
  with a row limit so nobody loops over a million rows by accident.

### 3.3 Sensitive values

Some outputs are secrets: a one-time code, a session token, a decrypted password. An operation marks
such an output `sensitive`. The engine then:

- never stores it in the database (the step record holds a placeholder);
- keeps it only in the run's encrypted scratch area until the run ends, then destroys it;
- masks it everywhere, exactly as a stored secret is masked;
- allows it to be mapped only into a **credential input** of another node, the same placement rule
  that secrets follow.

This lets a one-time code flow from the node that reads it to the node that types it without ever
appearing in a log, an output panel or the audit trail.

### 3.4 Connections

A **connection** is a named, typed set of settings for reaching one system: the non-secret parts
(host, port, tenant, base address) and references to the secret parts. It replaces typing
`{{ secret:name }}` into fields for almost every case.

```
connections(id, name, type, folder_id, settings jsonb, secret_names jsonb,
            environments[], allowed_hosts[], rate_limit, created_by, last_tested_at, last_test_ok)
```

- A connection type is declared by a connector (`oracle`, `sql-server`, `smtp`, `graph-mail`,
  `sftp`, `portal-login`, `http-bearer`).
- Each connection has a **Test** action that the connector implements (open and close a session,
  nothing more).
- One connection per environment is the norm: `Ledger (dev)`, `Ledger (prod)`. A node refers to a
  connection **by role name** (`ledger`), and the run's environment picks the real one. Promotion
  therefore never requires editing a workflow.
- The secret policy from ADR 0001 attaches here: hosts come from the connection's own settings, so
  the "allowed hosts" list is filled automatically and cannot drift.
- Rate limits are per connection, held in the database as a token bucket, so they hold across
  workers. A node that would exceed the limit waits, and the canvas says so.

### 3.5 Locks

Some systems allow one session at a time (a portal login that sends a one-time code to a shared
mailbox). A node can declare `lock: "<name>"`. The engine takes a named lock in the database before
dispatch and releases it when the node or a named later node finishes. Other runs wait in line and
show "Waiting for the supplier portal". Connections can declare a default lock.

## 4. Anatomy of a connector

A connector is a package (section 12 of the system design): a signed folder with a manifest and
Python modules.

```python
class Spreadsheet(App):
    key = "spreadsheet"
    name = "Spreadsheet"
    colour = "fern"
    icon = "table"
    trust = "built-in"
    limits = Limits(max_file_mb=200, memory_mb=1024)

    @operation(resource="Rows", kind="read", name="Read rows", version=1)
    def read_rows(self, ctx, inputs: ReadRowsIn) -> ReadRowsOut: ...

    @options("sheet")  # fills the Sheet drop-down at design time
    def list_sheets(self, ctx, values) -> list[Option]: ...

    @shape("read_rows")  # the columns this operation will output
    def read_rows_shape(self, ctx, values) -> TableShape: ...
```

| Part | Purpose |
|---|---|
| `App` | Identity: name, colour, icon, trust level, limits, connection types it accepts |
| `@operation` | One thing the app can do. Declares resource, kind, typed inputs and outputs, outcome ports, whether it has side effects, its pool, its timeout default |
| `@options` | A design-time call that fills a drop-down from live data (sheets in a workbook, tables in a schema) |
| `@shape` | A design-time call that returns the output columns, so downstream nodes can map them before any run |
| `@watch` | A polling trigger: given a cursor, return what is new. The scheduler stores the cursor |
| `@test` | Checks a connection |

**Operation kinds and what the engine does with them**

| Kind | Meaning | Retried automatically | Idempotency ledger | Runs in "Run this step" |
|---|---|---|---|---|
| `read` | Gets data, changes nothing | Yes | No | Yes |
| `find` | Search returning many | Yes | No | Yes |
| `convert` | File to file or table, inside the workspace | Yes | No | Yes |
| `write` | Creates something outside the workspace | Only on connection errors | Yes | Asks first |
| `change` | Updates or deletes outside the workspace | Only on connection errors | Yes | Asks first |
| `watch` | Trigger polling | n/a | Cursor | Yes (shows what would fire) |

**Design-time calls** (`@options`, `@shape`, `@test`) run in the same sandboxed runner as real
steps, with a 15 s limit, read-only, and their results are cached for five minutes per set of
values. They never run on the API process.

**Versioning.** `version=1` on an operation. A workflow version records the version it used. A new
version of an operation ships beside the old one; the old one is marked "newer version available"
in the Studio, with a preview of what changes.

## 5. The built-in connectors

These replace the 27 single-purpose activities of today. Each row is one node on the canvas.

| App | Colour | Connection | Resources and operations |
|---|---|---|---|
| **Spreadsheet** | Fern | none (workspace files), or a share | **Workbook**: create, list sheets, recalculate, protect. **Sheet**: read rows, write rows, append rows, clear, rename, copy. **Range**: read, write, format. **Table** (Excel table): read, append, update by key, delete by key. **CSV**: read, write. **Convert**: CSV to Excel, Excel to CSV, either to table |
| **PDF** | Hibiscus | none | **Document**: read text, read tables, page count, split, merge, rotate, reorder. **Pages**: to images, extract range. **Security**: protect, unlock. **Stamp**: watermark, page numbers. **Form**: read fields, fill fields |
| **Database** | Morning glory | Oracle, SQL Server, PostgreSQL, SQLite | **Query**: run query (to table), run query (single value). **Statement**: run statement, run script, call procedure. **Table**: load rows, upsert rows (staging then merge), list tables, describe table. **Transaction**: begin, commit, roll back (as a scope around other Database nodes) |
| **Files** | Marigold | share or local roots | **File**: copy, move, rename, delete, checksum. **Folder**: list, create, watch. **Archive to share**: copy with checksum verification and a retention label |
| **Archive** | Marigold | none | Zip, unzip (with entry and size caps), list entries, with passwords |
| **Email** | Orchid | Microsoft Graph, SMTP, IMAP | **Message**: send, reply, forward. **Mailbox**: find messages, read message, move, mark. **Attachment**: save to workspace. **Watch**: new message |
| **Web request** | Lagoon | bearer, basic, OAuth client, API key, none | Request (any method), download file, upload file, paged request (follows the next link) |
| **SFTP** | Lagoon | SFTP | Get, put, list, delete, move, watch folder |
| **Browser** | Iris | portal login | Open and act (recorded steps), download, upload, screenshot, read table from page |
| **Word** | Morning glory | none | Fill template, read text, convert to PDF |
| **Text** | Fern | none | Read fixed-width, read log, find by pattern, replace, split, template |
| **Code** (restricted) | Night soil | none | Run Python, run legacy robot |
| **AI** (off by default) | Iris | AI endpoint | Extract fields from a document, classify, summarise |

### 5.1 Spreadsheet in detail

The node an operations team will use most, so the design standard for all the others.

**Operations that matter**

| Operation | Inputs | Output | Notes |
|---|---|---|---|
| Read rows | file, sheet, header row, range (optional), columns (optional), types (auto or stated) | Table | Streams. Formula cells return their cached value; "recalculate first" is a switch |
| Write rows | file (new or existing), sheet, table in, start cell, write headers, mode (replace sheet, replace range, append) | File | Keeps charts, images and formats of an existing workbook |
| Update by key | file, sheet or Excel table, key column, table in, columns to update | File, plus counts (updated, not found) | Ports: `done`, `some not found`, `failed` |
| Find rows | file, sheet, conditions | Table | Conditions built with the rule builder |
| Format | file, sheet, range, number format, widths, freeze, header style, conditional rules | File | So reports leave finished |
| Recalculate | file | File, plus cells in error | Uses the built-in formula engine; lists unsupported functions it met |
| Read CSV | file, delimiter, encoding, quoting, header | Table | Encoding must be stated or confirmed; auto-detect only suggests |
| Convert | file in, target format | File or Table | |

**What makes it good**

- The **file** field accepts a file from an earlier node, a path in the workspace, or a file on an
  allowed share. Choosing a file fills **Sheet**; choosing a sheet shows a live preview of the first
  rows and fills the column pickers.
- Column types are detected and shown as editable chips above the preview (`amount: decimal`,
  `posted_at: date`). Fixing a type here fixes it for every node downstream.
- Limits are stated in the panel: file size cap, row cap, the 1900 date system only.
- Large files show progress on the node ("612,000 of 1,204,000 rows").

### 5.2 Database in detail

- **Connection first.** The node shows the connection role (`ledger`) and which real connection
  each environment resolves to. No address or password is ever typed in a workflow.
- **Query editor.** A SQL editor with completion from the live schema (through `@options`), named
  parameters (`:period_end`) listed beneath as fields that accept mapped values, and a **Preview**
  that runs with `FETCH FIRST 50 ROWS` and shows the result and its column types.
- **Read and write are separate operations with separate permissions.** `run query` is a `read`.
  `run statement` and `load rows` are `change` and `write`: they are idempotency-protected, they ask
  before running in "Run this step", and a connection can be marked **read-only** so they are
  refused.
- **Load rows** maps table columns to database columns in a two-sided mapper, with type checks
  before anything runs, loads into a staging table, then merges on the chosen key, and returns a
  table of rejected rows with reasons. Ports: `done`, `some rejected`, `failed`.
- **Transaction scope.** Dragging Database nodes into a Transaction group makes them commit or roll
  back together.
- **Safety.** Statements are parsed before dispatch. A statement with no `WHERE` on `UPDATE` or
  `DELETE`, or any DDL, needs the connection to allow it and is flagged for the approver at
  promotion.

### 5.3 PDF in detail

- **Read tables** shows the page with detected table regions outlined; the author can adjust a
  region by dragging, and the choice is saved as coordinates so the run is repeatable.
- **Split** takes a rule: every N pages, at bookmarks, or where text matches a pattern (for example
  each new invoice number). Output is a list of files.
- **Merge** takes a list of files with drag-to-order.
- **Fill form** reads the field names from the PDF and offers each as a mappable field.
- Encrypted input is detected up front and asks for a password connection, instead of failing at
  run time.

## 6. Skill nodes

A skill is a node designed around one behaviour. It has what an app node has (typed inputs and
outputs, ports, a version) plus three things:

| Extra | Meaning |
|---|---|
| **A designed setup** | Its own layout built from the widget library (section 8.4), in the order a person thinks about the task |
| **Named outcomes** | Ports that say what happened in business terms (`all matched`, `has unmatched`), not just done or failed |
| **A result view** | A purpose-built summary of what it did, shown on the run page and in the Studio after a test |

Skills are built two ways, and the author cannot tell which:

- **Native**: Python, like an operation, for behaviours that need their own algorithm (Match).
- **Composite**: a packaged sub-workflow with a custom setup screen in front of it (Portal sign-in
  is Browser plus One-time code plus session reuse). Composite skills can be created in the Studio
  from a selection ("Save as skill") and shared within the organisation.

### 6.1 Match

*Pairs the rows of two tables and tells you what is left over.*

| | |
|---|---|
| **Inputs** | Left table, right table |
| **Setup** | 1. **Pair on**: one or more key pairs chosen from the two tables' columns, each with a comparison (exact, ignore case, ignore spaces, ignore leading zeros, pattern). 2. **Also require**: amount within a tolerance (absolute or percent), date within N days. 3. **How**: one to one, one to many, many to many (sum to match). 4. **If several could match**: closest amount, closest date, first. 5. **Carry over**: which columns from each side appear in the results |
| **Outputs** | `matched` (table), `unmatched_left` (table), `unmatched_right` (table), `summary` (record: counts, totals, difference) |
| **Ports** | `all matched`, `has unmatched`, `failed` |
| **Result view** | A bar split into matched, left only and right only with counts and totals; the three tables as tabs; the rules that were applied |
| **Test** | Runs on the pinned tables and shows the result view live as rules are changed, so tolerance can be tuned by eye |
| **Pairs naturally with** | Manual match (a human task that receives the two unmatched tables and returns pairs and write-offs) |

### 6.2 One-time code

*Gets the code a system has just sent, and hands it on without anyone or anything seeing it.*

| | |
|---|---|
| **Sources** | **Mailbox** (Graph or IMAP connection): the newest message from a sender after a point in time. **Authenticator** (a stored TOTP seed): computes the code. **Text message** (an SMS gateway that posts to a webhook). **Ask a person**: creates a short task with a code field |
| **Setup** | 1. Source and its connection. 2. **Only codes sent after**: "this node started" or "the start of *node X*" (pick the node that triggers the code, so an older message is never used). 3. **From**: sender address or number. 4. **Find the code**: presets (6 digits, 4 to 8 digits, letters and digits) or a pattern, with a **tester**: paste a sample message and the code is highlighted. 5. **Wait up to** and **check every**. 6. **After reading**: leave, mark read, or delete |
| **Outputs** | `code` (**sensitive**, section 3.3), `received_at`, `sender` |
| **Ports** | `received`, `timed out`, `failed` |
| **Lock** | Takes the mailbox's lock from the node chosen in step 2 until the code is read, so two runs can never read each other's code |
| **Engine behaviour** | Waiting does not hold a worker. The node polls on a timer with a short worker job each time |
| **Result view** | When it arrived, how long the wait was, from whom. Never the code |

### 6.3 Portal sign-in (composite)

*Signs in to a website, with a one-time code if needed, and keeps the session for later nodes.*

Setup: the portal connection (address, user, password reference, sign-in type), the fields to fill
(picked by clicking them in a recorded preview), where the code goes, and how to tell the sign-in
worked. Output: a `session` (sensitive) that Browser nodes accept. It reuses a saved session when
one is still valid and signs in again only when it is not. Ports: `signed in`, `rejected`,
`code timed out`, `failed`.

### 6.4 People skills

The four task types become four skills, each with a designed form and named ports:

| Skill | Ports |
|---|---|
| **Approval** | `approved`, `rejected`, `timed out` |
| **Manual match** | `completed`, `timed out` (outputs pairs and write-offs as tables) |
| **Data entry** | `submitted`, `timed out` (the form is built in the setup with a field list) |
| **Exception** | `resolved`, `written off`, `escalated`, `timed out` |

### 6.5 More skills to build

| Skill | Behaviour | Ports |
|---|---|---|
| **Validate** | Check a table against rules (required, type, range, pattern, unique, exists in another table) | `all valid`, `has invalid` (with a table of failing rows and reasons) |
| **Compare** | What changed between two versions of a table: added, removed, changed rows by key | `same`, `different` |
| **Remove duplicates** | By chosen columns, keep first, last or best | `done` |
| **Build report** | A table or several into a formatted Excel or PDF from a template | `done` |
| **Notify** | Tell people by email, Teams or in-app, from a template, with the run's summary | `sent` |
| **Wait for file** | Wait until a file appears on a share or SFTP, with a deadline | `arrived`, `timed out` |
| **Check totals** | Assert that two totals agree within a tolerance, and stop the workflow if not | `balanced`, `out of balance` |

## 7. Flow and data tools

Run by the engine itself or as light table jobs. Kept few on purpose.

| Tool | Does |
|---|---|
| If, Switch | Route by condition or by rules, with a default |
| Parallel, Merge | Do several things at once; wait for all, any, or N |
| Loop | Run a group of nodes per item of a list, with a concurrency setting |
| Wait | For a duration, until a time, or for a signal |
| Set values | Compute named values for later nodes |
| Stop | End the run as done or failed with a message |
| Filter rows, Pick columns, Rename, Sort, Limit | Simple table shaping |
| Join | Combine two tables on keys (inner, left, full) |
| Group and total | Sum, count, min, max, average by columns |
| Add column | A computed column from an expression |
| Table to list, List to table | Cross between the two worlds, with a row cap |

Table tools are implemented once on a columnar engine in the worker and all take and return table
handles, so a chain of five of them never loads a file fully into memory.

## 8. UI design

### 8.1 Adding a node

Opening the add menu (the bud on a stem, the library rail, or `Tab`):

```
+----------------------------------------------+
| [ Search: read excel                       ] |
|----------------------------------------------|
| Suggested after "Download statement"         |
|   (flower) Spreadsheet    Read rows          |
|   (flower) Archive        Unzip              |
|----------------------------------------------|
| Apps      Skills      Flow      Data         |
|                                              |
|  (o) Spreadsheet   (o) PDF      (o) Database |
|  (o) Files         (o) Email    (o) Web      |
|  (o) SFTP          (o) Browser  (o) Word     |
+----------------------------------------------+
```

- **Search understands verbs and nouns**: "read excel", "send mail", "match", "otp" all find the
  right node and operation. Results are operations, not just apps, so one `Enter` adds the node with
  the operation already chosen.
- **Suggested** is driven by the type coming out of the previous node: after a File that is a ZIP,
  Unzip comes first; after a Table, Match, Filter rows and Write rows.
- Choosing an app without an operation opens its operation list grouped by resource, each with a
  one-line description and its kind marked (read, write, change).
- Restricted nodes show a small lock and say who may use them.

### 8.2 The node on the canvas

- **Flower in the app's colour**, the app's glyph in the centre, the operation as the label and one
  line of summary beneath it written from the settings: "Read rows, *Invoices* sheet".
- **Skills** have pointed petals. **People** skills are sunflowers.
- **Ports** appear as small buds on the right edge, named on hover; a node with business outcomes
  shows the names always (`all matched`, `has unmatched`).
- **Stems** carry the type: a thick stem with a row count for a table, a thin one with a small file
  mark for a file, a hairline for a record. A sensitive value travels on a dotted stem with a small
  lock, and its label is never shown.
- **States**: the petals fill clockwise while running; a progress count sits under the label for
  long table work; waiting for a lock or a rate limit shows a small hourglass bud and a sentence on
  hover; a node with a problem wears a hibiscus dot.
- **Needs attention before it can run** (no connection chosen, a required field empty): the flower
  is outlined instead of filled, so an unfinished node is obvious.

### 8.3 The setup panel for an app node

Top to bottom, always in this order, so every app feels the same:

1. **Header**: flower, app name, operation as a drop-down (change it without re-adding the node),
   a link to the app's help, "Run this step".
2. **Connection** (if the app needs one): the role name and the connection each environment
   resolves to, a status dot from the last test, **Test**, and "New connection" for those allowed.
3. **What to work on**: the cascading pickers (file, then sheet; connection, then schema, then
   table). Each fills from live data and shows a small spinner inside the field while it loads,
   never blocking the rest of the form.
4. **Preview strip**: the first rows or the first page of what was picked, so the author knows they
   chose the right thing.
5. **Settings** for the operation: only the fields this operation uses. Each accepts a typed value
   or a mapped value from an earlier node.
6. **Options**: collapsed; the rarely needed fields.
7. **Outcomes**: what each port means for this operation.
8. **Behaviour**: retry, timeout, on failure, lock, notes.
9. **Limits and notes**: the connector's declared limits in one quiet line ("Files up to 200 MB.
   Formulas use the built-in engine.").

**Mapping** a value: click a field, and the Input tab lights up with everything that can go there.
Values of the wrong type are dimmed with the reason on hover. Dragging a table column into a field
that wants a column name inserts the name; dragging it into a field that wants a value inserts a
reference to that column for the current row.

### 8.4 The widget library

Setup screens for apps and skills are declared, not coded, from a fixed set of widgets. A package
cannot ship its own scripts; this keeps third-party nodes safe and every node consistent.

| Widget | Used for |
|---|---|
| Text, number, date, switch, choice | Plain values |
| **Connection picker** | Choosing a connection role |
| **File picker** | A file from an earlier node, the workspace or an allowed share |
| **Cascading picker** | Sheet in workbook, table in schema |
| **Column picker** | One or many columns of an input table, with types |
| **Column mapper** | Two lists side by side with lines between them (Load rows, Match keys) |
| **Rule builder** | Rows of column, comparison, value with and/or (Filter, Find, Validate, Switch) |
| **Tolerance** | A number with a unit switch (absolute, percent, days) |
| **Pattern tester** | A pattern field, a sample box, live highlights (One-time code, Text) |
| **Query editor** | SQL with schema completion and named parameters |
| **Template editor** | Text with mapped values as chips (Email body, Notify) |
| **Page region picker** | Draw regions on a page preview (PDF read tables) |
| **Step recorder** | A list of browser actions with a preview (Browser, Portal sign-in) |
| **Table preview** | First rows with editable column-type chips |
| **Form designer** | A field list for a Data entry task |

### 8.5 Skill setup screens

A skill's panel opens wide by default (two thirds of the window) because its setup is a small tool,
not a form.

**Match**

```
+------------------------------------------------------------------+
| (dahlia) Match                         [Run this step]  [x]      |
|------------------------------------------------------------------|
| Left: Ledger postings (1,204 rows)   Right: Invoices (1,198 rows)|
|                                                                  |
| 1  Pair on                                                       |
|    reference   ───────────────  invoice_id     ignore zeros  [x] |
|    [+ add a pair]                                                |
| 2  Also require                                                  |
|    amount  ─── amount    within  0.005  [absolute v]             |
|    posting_date ─ posted_at  within  3  days                     |
| 3  How      (o) one to one   ( ) one to many   ( ) many to many  |
|------------------------------------------------------------------|
|  Result on the pinned data                                       |
|  [=============== 1,164 matched ===============][ 40 ][ 34 ]     |
|   Matched | Left only (40) | Right only (34)                     |
|   reference   amount     invoice_id   amount    difference       |
+------------------------------------------------------------------+
```

The result at the bottom recomputes within a second of any change, on the pinned tables. Tuning a
tolerance is a matter of moving a number and watching the bar. *Feel: an instrument. The author is
adjusting, and the node answers.*

**One-time code**

Four large source choices across the top (Mailbox, Authenticator, Text message, Ask a person).
Below, a short vertical story in plain sentences with the controls inline:

> Read the newest message in **ops@ mailbox** from **no-reply@portal.example** that arrived after
> **Sign in started**. Find **6 digits**. Wait up to **2 minutes**, checking every **5 seconds**.
> Then **mark it read**.

Under it the pattern tester: paste a sample message, the code lights up. A note says, in one line,
that the code will never be shown or stored. *Feel: reassuring and short. A person should finish it
in thirty seconds and trust it.*

### 8.6 Results

- On the run page and after a test, an app node shows its output by type: a table as a grid with
  column types, row count and download; a file as a preview with its size and checksum; a record as
  a tree.
- A skill shows its result view first (the Match bar, the Validate breakdown), with the raw outputs
  behind a tab.
- A sensitive output shows a lock and the words "Hidden. Passed to Sign in."

### 8.7 Connections screen

(The Connections area of the console, replacing a plain secrets list.)

- A gallery of connections grouped by type, each a card with the app flower, the name, the
  environments it serves as three small dots, its last test result and where it is used.
- **New connection** is a three-step sheet: choose the type, fill the type's own form (with the
  secret fields typed once and never shown again), **Test**. A connection cannot be saved untested
  unless the person says so explicitly.
- A connection's page shows its settings, its policy (environments, folders, read-only, rate
  limit), the workflows and nodes that use it, its recent uses and its history.
- A failed test explains itself in the system's own words and in plain words: "The database refused
  the sign-in (ORA-01017). Check the user name and password."

### 8.8 Packages screen (Admin)

Installed connector and skill packages with version, signer, trust level and the nodes each
provides. Upload, verify signature, enable per folder, disable. A package's page lists each node's
operations with their kinds and limits, generated from the manifest: this is WorkTree's equivalent
of a connector reference page.

## 9. System design additions

Changes to `02-system-design.md` that this design requires:

| Area | Addition |
|---|---|
| Workflow schema | A node names `app` and `operation` (or `skill`) and a pinned operation version. Ports are named by the operation. Edges carry a declared type |
| Validation | Type checking across edges; connection role resolvable in every environment the workflow is promoted to; sensitive values only into credential inputs |
| Engine | Table and file handles as first-class output values; sensitive scratch storage per run; named locks; per-connection rate limiting; polling nodes that do not hold a worker |
| Worker | A columnar table engine for the data tools; design-time call queue (`options`, `shape`, `test`) with its own small pool and cache |
| API | `GET /nodes` (catalogue), `GET /nodes/{app}/operations/{op}` (schemas), `POST /nodes/{app}/options/{field}`, `POST /nodes/{app}/shape/{op}`, `connections` CRUD and `POST /connections/{id}/test`, `packages` |
| Data | Tables `connections`, `connection_uses`, `locks`, `rate_buckets`, `trigger_cursors`, `design_cache`, `packages`, `package_nodes` |
| Security | Connections carry the secret policy; write and change operations gated by connection read-only flag and by role; statement checks for Database; packages signed; setup screens declarative only |
| Migration | Each of today's 27 activities maps to one operation or skill (table below); stored workflows keep running through an adapter that presents the old activity names |

### 9.1 Mapping today's activities

| Today | Becomes |
|---|---|
| `excel`, `csv`, `spreadsheet` | Spreadsheet |
| `pdf` | PDF |
| `document` | Word |
| `gl_query`, `oracle_query` | Database: run query |
| `oracle_execute` | Database: run statement |
| `oracle_bulk_load` | Database: load rows / upsert rows |
| `http_request`, `download_file` | Web request |
| `sftp` | SFTP |
| `email` | Email: send |
| `graph_read_mail` | Email: find messages, and the One-time code skill |
| `unc_archive` | Files: archive to share |
| `zip` | Archive |
| `txt_log` | Text |
| `playwright_robot`, `playwright_script` | Browser, and the Portal sign-in skill |
| `matching` | Match skill |
| `human_task` | Approval, Manual match, Data entry, Exception skills |
| `ai_extract` | AI: extract fields |
| `run_python`, `legacy_robot_wrapper` | Code (restricted) |
| `echo`, `sleep`, `fail` | Set values, Wait, Stop |

### 9.2 Build order

1. The value types and table handles in the engine and the runner (everything depends on them).
2. Connections, with the secret policy attached.
3. The connector framework (`App`, `@operation`, `@options`, `@shape`) and the adapter for old
   activity names.
4. Spreadsheet, Database, Files and Web request as the first four apps.
5. The widget library and the app setup panel in the Studio.
6. Match and One-time code as the first two skills, including sensitive values and locks.
7. The remaining apps, then the remaining skills, then "Save as skill".
