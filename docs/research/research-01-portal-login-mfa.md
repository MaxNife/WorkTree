# Research 01: portal logins and MFA (2026-09-29)

## Context
- Hope's team's automation work is mostly a mix of: portal downloads, Oracle DB ETLs, file CRUD, and mail sending. The two test projects (Excel -> compute -> share/Graph, and portal -> format -> DB) represent the bulk.
- Portal logins vary per portal, and all three types occur: API token, plain login form, browser login with MFA.
- Most OTPs are EMAIL codes, and the team already fetches them with the Graph API today.
- Playwright use is already approved.
- Research phase only. Nothing is being planned or built yet.

## Findings
| Login type | Automatable? | How |
|---|---|---|
| API token / key | Yes, no browser | HTTP call (Elsa `DownloadHttpFile` covers it). Secret storage is the real concern |
| Username + password form | Yes | Playwright logs in once, saves session state, reuses it until it expires |
| MFA: email code (most portals) | Yes | Playwright triggers login, workflow reads the code from the mailbox via Graph. See research-02 |
| MFA: TOTP (authenticator code) | Yes, technically | Store the shared secret, generate the code in the script. Weakens MFA (server holds both factors), so needs security sign-off |
| MFA: push approval (e.g. Authenticator app) | No | Needs a person's phone. Sources say so |
| MFA: SMS code | No | Same |

## Playwright notes
- Saved session state (cookies, local storage) is a credential: treat like a password, never commit it. Playwright docs do NOT cover session expiry or refresh, so re-login-on-failure is our design job.
- Session storage is not persisted by Playwright natively (docs give a workaround).
- Session lifetime is decided by each portal, not by Playwright.
- Restricted networks: Playwright supports `PLAYWRIGHT_DOWNLOAD_HOST` (mirror), `PLAYWRIGHT_BROWSERS_PATH`, proxy/CA env vars, and using an installed Chrome/Edge via `channel`. Branded Chrome/Edge headless behaves slightly differently from Playwright's own headless shell.

## Elsa: human in the loop (for any push/SMS portal)
- `Elsa.UserTasks` has a `UserTask` activity (verified in elsa-core code): it creates a task, suspends the workflow with a bookmark, and resumes when a person completes it. Supports assignee/candidate groups, due date, a timeout outcome, and completion data comes back as the result.
- Not yet checked: whether that completion data can cleanly carry a one-time code, and how a person would see/complete the task (Studio vs API).

## Source quality
- Playwright auth doc is official. The MFA sources are blog posts (M365 article by Elio Struyf, a GrowwStacks post); they agree with each other but treat as leads, not gospel.

## Open / next
- Which portals need push or SMS (cannot be unattended)? A rough count would show how few need a human.
- For push/SMS portals: ask portal owner about a service account, IP allowlisting, API, or SFTP; otherwise human-in-the-loop.
- Remaining research topics: Oracle access, Excel libraries/licences, secrets handling, Elsa gaps (retries, scheduling, Studio, release vs main).

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30; [tested] = capability tested; [docs] = official page/README; [reasoning] = inference.
.NET limit: NuGet is blocked in the sandbox, so Playwright for .NET could NOT be run. It is [docs] only.

### What is the same in every language
- Playwright's own docs: "All core features for automating the browser are supported in all languages, while testing ecosystem integration is different." [docs, playwright.dev/docs/languages]
- The Python package ships a bundled Node.js driver (I found `playwright/driver/node` inside the installed Python package) [tested]. My recollection is that the .NET package works the same way; not verified. So the languages are thin clients over one shared core, which is why they behave alike.
- Same job in Node and Python: launch Chromium, wait for a table built by JavaScript, read it, save a PDF, a screenshot and (Node) the session state. Node total 1.43 s (browser launch 591 ms); Python total 1.38 s (launch 725 ms) [measured, single runs]. A tie: the browser does the work.
- Session-state saving (`storageState`) worked in Node [tested]. I did not re-check the .NET and Python docs for it in this pass.

### What differs
- Test runner: Node has its own (@playwright/test: parallel runs, HTML report, tracing); Python has a pytest plugin; .NET has MSTest / NUnit / xUnit / xUnit v3 base classes [docs]. That matters for testing web apps. It matters little for unattended automation scripts.
- .NET install: the docs' setup step installs browsers with a PowerShell script, and recommend .NET 8 [docs]. On a locked-down machine that is one more thing to approve; the mirror and installed-Chrome options in the notes above apply to all languages.
- Versions I saw: Node package 1.63.0 (npm, 2026-09-30); the Python package pip gave me here was 1.56.0. Do not read anything into it yet; pin one version per language and check what is actually approved.

### VERDICT: multi-language for Playwright, with clear roles
Playwright is a scripting tool, so it can stay multi-language (Hope's rule).
1. Platform-owned building blocks (the reusable "log in with email-code MFA", "download report", "save session state") in .NET: the same runtime as the runner, an official NuGet package, and no extra runtime for the organisation to approve. [reasoning]
2. Project-specific portal scripts in whatever the script author knows: Python (the team's main language) or JavaScript, run in a worker under the shared node contract (small JSON in, files and JSON out, secrets passed for one call, timeout, named "Failed" outcome).
Speed and feature set do not separate the languages; maintainability does.
Open question for Hope: the Playwright approval, is it tied to one language package (probably the Python one the team uses today)? If so, .NET and Node need their own approval before they can be used.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The login-type table applies unchanged. `playwright_robot` implements API token, form, and form + email OTP (`BUILD_PROMPT:59`).
- TOTP is not in the MVP spec. Push/SMS MFA cannot be unattended; the MVP spec does not cover them. A Data Entry human task is the natural fit [inferred].
- Playwright notes (session state is a credential; re-login on failure is our design job; restricted-network env vars) apply to the Python build.
- Elsa `UserTask` → our `human_task` activity.
- Language verdict superseded: Playwright is Python only (both platform login blocks and project scripts).
