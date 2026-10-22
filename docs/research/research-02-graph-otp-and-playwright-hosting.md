# Research 02: reading OTP emails via Graph, and where Playwright runs (2026-09-29)

Sources: Microsoft Learn (Graph list messages; RBAC for Applications in Exchange Online) and Playwright .NET docs (Docker, library). Items marked (my reasoning) are inferences, not from the docs.

## Graph is now a core piece, not a side feature
Graph would be used for: reading OTP emails, sending mail, and delivering files (Project 1). Elsa has no Graph activity (its `SendEmail` is SMTP/MailKit), so a Graph module is a foundation piece to build.

## Reading OTP emails via Graph
- Endpoint: `GET /users/{id|upn}/messages` (or `/mailFolders/{id}/messages`). Supports `$filter`, `$orderby`, `$top`, `$select`. Default page size 10.
- `$filter` + `$orderby` restriction: properties in `$orderby` must also be in `$filter`, in the same order, and before any filter properties not in the orderby. Breaking it gives `InefficientFilter`. So `receivedDateTime gt <time>` with `$orderby=receivedDateTime desc` is valid. Combining with a sender filter should also work if receivedDateTime comes first (untested).
- Use `$select` to keep responses small (docs warn of 504 gateway timeouts otherwise). Message bodies come back as HTML by default.
- Permissions: application `Mail.Read` (higher) or `Mail.ReadBasic.All` (lowest, but likely without body, so probably not enough for reading codes: to verify).

## Limiting the app to only the OTP mailbox(es) (security-relevant)
- Application `Mail.Read` in Entra ID gives access to every mailbox in the tenant unless scoped.
- Current mechanism: RBAC for Applications in Exchange Online (replaces the older Application Access Policies). Steps: create a service principal pointer, optionally a management scope, then assign role `Application Mail.Read` (or `Mail.Send`, etc.) with that scope; test with `Test-ServicePrincipalAuthorization`.
- Entra and Exchange permissions add together, so unscoped Entra consent must be removed or the scope does nothing.
- Needs Exchange Administrator; changes can take 30 min to 2 hours to apply (cache).
- Worth asking the Exchange/security team which mechanism they already use for the existing Graph OTP reader.

## OTP timing design points (my reasoning)
- Record the time just BEFORE triggering the login, then poll for a message received after that time from that portal's sender, taking the newest. This avoids stale codes.
- If two logins to the same portal run at once, the codes can get mixed up: serialise logins per portal (or per mailbox).
- Codes expire, so poll with a timeout and a retry that requests a fresh code.

## Where Playwright runs
What the docs say:
- Chromium can crash out of memory in containers without shared-memory settings (`--ipc=host`), and needs `--init` to avoid zombie processes.
- Running as non-root with a seccomp profile is recommended for untrusted sites; running as root disables the Chromium sandbox.
- Used as a library: `Playwright.CreateAsync()` then launch a browser; multiple isolated contexts per browser are supported. The docs do not spell out a threading/concurrency model.
Design implication (my reasoning): browsers are heavy, can crash, and visit external sites, so keeping them in a separate worker/container (not inside the Elsa server process that runs every workflow) limits the blast radius. This fits the earlier isolated-worker plan. Not yet decided.

## Not yet checked
- Whether Mail.ReadBasic is enough for OTP bodies (probably not)
- Graph throttling limits for frequent polling; change notifications as an alternative to polling
- Graph file upload to SharePoint/OneDrive (for Project 1), and large-file upload sessions
- Playwright concurrency limits per worker

## Language verdict: .NET vs JavaScript vs Python (added 2026-09-30)

Evidence tags: [measured] = run in this sandbox on 2026-09-30; [tested] = capability tested; [docs] = official page/README; [reasoning] = inference.
Limits: no Microsoft 365 tenant in the sandbox, so no Graph call was made in any language; NuGet is blocked, so no .NET package could be run. Everything about Graph below is [docs] or [reasoning].

### Graph (reading OTP mail, sending mail, delivering files)
| Language | Official SDK | Status [docs] |
|---|---|---|
| .NET | `Microsoft.Graph` (MIT) | Generally available; targets .NET Standard 2.0; releases on a fixed schedule (second and fourth weeks of each month) |
| Python | `msgraph-sdk` (MIT) | Appears generally available (repo README shows no preview banner; the fetch could not confirm a version) |
| JavaScript | `@microsoft/microsoft-graph-client` 3.0.7 (MIT, updated 2026-07-16) | Published and maintained (README shows no deprecation notice). The newer Kiota-based TypeScript SDK (`@microsoft/msgraph-sdk`, npm 1.0.0-preview.90) says on its own README: "currently in Pre-Release" |
- Sign-in libraries exist in all three (`@azure/identity` 4.13.3, MIT, is the one I checked; Python and .NET equivalents are standard, not looked up). Client-secret sign-in (the current method, research-17) is supported by them; not tested.
- Graph is a plain REST API, so any language (or Elsa's own HTTP activities) can call it without an SDK.
- Speed: Graph calls wait on the network and on Microsoft's throttling, so language speed is irrelevant [reasoning]. Not measured.
- Fit: Elsa has no Graph module and it must be built as a foundation piece (above). That is a .NET job either way.

### VERDICT (Graph): .NET
Reason: it is the only one whose official SDK is clearly generally available AND written in the runner's own language, so the mail-send, OTP-read and file-delivery nodes can be platform nodes with native retry hooks (research-18) and no extra runtime. Python is a fine second (also GA); JavaScript is last because its newer SDK is still pre-release.
This is a lean, not a proof: nothing could be run against a real tenant. Test it once with a real read of the OTP mailbox and a send.
The OTP reader the team already runs today is a useful reference for the mailbox query and the RBAC scope.

### Playwright hosting
See research-01 for the language verdict (multi-language; same speed and features). The hosting advice above (separate worker or container, non-root, `--ipc=host`, `--init`) applies unchanged to Node and Python bindings; the .NET docs cited here are the ones I read.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The Graph OTP query rules, mailbox scoping (RBAC for Applications in Exchange Online) and OTP timing rules apply unchanged. They are built into `graph_read_mail` and `playwright_robot` (`BUILD_PROMPT:57,59`).
- Language verdict superseded: Graph is Python. Options from this note are `msgraph-sdk` (MIT, appears GA) or direct REST calls. The build agent chooses and records the choice in `DECISIONS.md`. Nothing has been run against a real tenant; tests use the fake Graph server, and the real-tenant gap goes in `KNOWN_GAPS.md`.
- Playwright hosting advice (separate process, non-root, `--ipc=host` and `--init` if containerised) applies to the Python worker. Docker is optional in the MVP.
