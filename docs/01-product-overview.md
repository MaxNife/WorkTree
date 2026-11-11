# WorkTree: what the product is

Written 2026-11-11 from a full read of the repository. This is the plain-language description of
the product. The target design is in `02-system-design.md`; how to get there from today's code is in
`03-upgrade-guide.md`.

## In one paragraph

WorkTree is an on-premise automation platform for an operations or finance team. It replaces
hand-written scripts started by Windows Task Scheduler with workflows that are built from reusable
steps, run on a schedule or on demand, pause when a person has to decide something, and leave a
complete record of who did what. Engineers build the workflows, process owners run and watch them,
and approvers and auditors get proof that the controls were followed.

## The problem it solves

The team it is built for runs dozens of automations that all look alike: log in to a supplier or
bank portal (often with a one-time code sent by email), download a file, clean it, compare it with
the ledger in Oracle, produce an Excel report, email it and archive it to a network share. Today
each one is its own script on its own server. That causes five problems:

| Problem today | What WorkTree does about it |
|---|---|
| Every script re-implements login, download, parsing and email | One governed library of activities. A workflow is configuration, not code |
| Nobody knows a job failed until the report is missing | A live console: every run, every step, its duration, its error and its files |
| Passwords sit in config files and environment variables | A secret store. Workflows name a secret; only the worker that needs it ever sees the value |
| A person fixes exceptions by email and nothing records the decision | Human tasks: the run pauses, a named person decides, the reason is recorded, the run continues |
| Changes go straight to production with no review | Immutable versions, dev to test to prod promotion, and the author cannot approve their own work |

## Who uses it

| Role | What they do in WorkTree |
|---|---|
| **Viewer** | Reads dashboards, run history and results |
| **Operator** | Starts and retries runs, works the task inbox |
| **Author** | Builds and tests workflows in dev and test, requests promotion |
| **Approver** | Approves promotions and business decisions, reads the audit log |
| **Admin** | Manages users, secrets, schedules and environments; the only role that may use code-running activities |

## The ideas you need

- **Workflow.** A named graph of steps with settings (owner, SLA, what to do if it is already
  running). Stored as data, shown as a canvas, editable as YAML.
- **Step.** One box in the workflow. It names an activity, gives it inputs and says where to go
  when it finishes or fails.
- **Activity.** A reusable tool, one Python class each: read a CSV, query Oracle, drive a browser,
  send an email, match two tables. There are 27 today. An activity never crashes the platform: it
  returns `done` or `failed` with a safe message.
- **App and skill.** The target design groups activities the way authors think. An **app** is one
  node for one tool with many operations inside it: Spreadsheet (every Excel and CSV action), PDF,
  Database, Files, Email, Web request. A **skill** is a node built for one business behaviour, with
  its own setup screen: Match pairs two tables and reports what is left over; One-time code fetches
  a sign-in code without anyone seeing it. More skills are added as the business needs them.
- **Connection.** A named, tested way of reaching a system (the ledger database, a mailbox, a
  portal). Authors pick a connection; they never type an address or a password.
- **Run.** One execution of one version of a workflow, in one environment. It has its own
  workspace folder where steps pass files to each other by path, so a three-million-row file never
  travels through memory or the database.
- **Trigger.** What starts a run: a schedule, a webhook, a file arriving in a folder, another
  workflow finishing, or a person pressing Run now.
- **Task.** Work for a person. Four kinds: approval, manual match, data entry and exception
  disposition. A task has an assignee role, a due time and a recorded decision.
- **Version and promotion.** Saving a workflow makes a new immutable version. Production runs only
  a version that was approved in test and then approved for prod by someone other than its author.
- **Secret.** A named credential. Workflows hold `{{ secret:name }}`, never the value. Values are
  masked wherever text is shown or logged.
- **Artifact.** A file a step chose to publish from the workspace: a report, a screenshot, a list
  of unmatched rows.
- **Audit log.** An append-only, hash-chained record of every change and every run event.

## A day with WorkTree

At 06:00 the schedule starts *Invoice reconciliation*. The browser robot logs in to the supplier
portal, reads the one-time code from the operations mailbox and downloads an encrypted ZIP. The
file steps extract a one-million-row CSV and stream it to Parquet. A query pulls the period's ledger
postings. The matching step pairs them by reference, amount and date. Forty rows do not match, so
the run pauses and a manual-match task appears in the inbox for Operators, due in four hours. Kemi
claims it, pairs thirty-eight rows, writes off two with a reason, and completes it. The run
resumes, builds the Excel report, emails it and archives it with a checksum. Tunde, an approver,
later opens the run and sees every step, every file and Kemi's decision with its reason. Nobody
touched a server.

## What it is not

- Not a cloud service. It installs on the organisation's own servers and makes no outbound calls
  that a workflow did not ask for.
- Not a general integration marketplace. The activity library is deliberately small and governed.
- Not a sandbox for untrusted code. Code-running activities are restricted to Admins, and the
  target design isolates them further.
- Not built on another engine. Elsa Workflows is the model for engine behaviour and n8n and Make
  for the builder experience. Neither is a dependency, and no code or assets are copied.

## Where it stands today

| Area | State |
|---|---|
| Engine, workers, queue, triggers, human tasks, audit, auth, promotion | Built and tested (453 backend tests) |
| Activity library | 27 activities built. Real Oracle, Microsoft Graph, SFTP and portals are untested; they run against local fakes |
| REST API and live events | Built: 59 API routes, a health check and one WebSocket |
| Web console | App shell, sign-in and Operations (dashboard, runs, run detail, schedules, Run now) are built. Inbox, Studio, Data and Admin are placeholders |
| Branching beyond done or failed, parallel steps, conditions | Not in the engine. The canvas designs assume them |
| Secret scoping and outbound host control | Decided (ADR 0001), not built |
| Continuous integration, production runbook | Not built |

## Product principles

1. **Governed before flexible.** Every capability arrives with its audit record, its permission
   and its masking, or it does not arrive.
2. **Files by reference.** Steps exchange paths and small summaries. Big data stays on disk.
3. **Nothing fails silently.** A failure is a named outcome with a message, a route and an alert.
4. **People are part of the workflow.** A human decision is a first-class step with an owner, a
   deadline and a reason.
5. **A garden, not a filing cabinet.** The product looks like what it is named after: plant
   shapes and seven flower colours on a clean light base. Every area has a colour and every
   workflow a flower, while tables and forms stay white and easy to read.
6. **One server is enough to start.** SQLite and a single process by default; the same design
   scales out without a rewrite.

## Names

The product is **WorkTree**. Code identifiers, the command line (`uaf`), the cookie names and the
environment prefix (`UAF_`) still carry the earlier working name. The upgrade guide renames them.
