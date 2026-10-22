# Research 16: a node library that grows with each project (2026-09-29)

## Requirement from Hope
For each new project the team may need to set up new nodes, and future projects should inherit them. RESOLVED: "inherit" means reuse a saved custom node AS IS in other projects. No derive-and-change/override is needed (Elsa has none anyway). The node set is not fixed at about 8: the file-tool nodes (research-05 to 14) are the starting platform nodes, and project nodes grow on top. This supersedes the "only about 8 nodes" assumption in research-14.

## Three ways Elsa lets us add nodes (verified in code; nothing built or run)
1. Save a workflow as a node (no code). Confirmed in Studio's source: in a workflow's Settings there is a "Usable as activity" checkbox, and when ticked an activity category field appears (default category "Workflows"). Once published, the workflow shows in the designer's picker as a node (`WorkflowDefinitionActivityProvider`), with inputs (name, display name, description, category, UI hint, type), outputs and outcomes (as ports) taken from the workflow's own input/output/outcome definitions. Example: "Portal X download" = login + read email code via Graph + download, built once and reused everywhere.
   - How it runs: the node is a composite that loads the saved workflow at run time and runs it INLINE inside the calling workflow's instance (not as a separate instance); inputs are copied into variables, outputs copied back. So large values in its outputs are persisted with the parent (research-04).
   - Versioning: descriptors exist for every version; each node instance pins the version it was created with and knows the latest published version ("tooling uses this to let the user know that a newer version is available", per the code comment). Studio has a Version tab on a selected node listing versions and letting you change the node's version (a version not usable as activity is greyed out). Old workflows keep their pinned version.
2. Catalogue-driven nodes backed by a worker (no C# per node): a custom `IActivityProvider` turns entries the Python worker publishes into nodes, the way Elsa does for configured AI agents (research-14/15). Generated ("synthetic") inputs are simple; the dependent-dropdown refresh probably does not work for them (my reasoning, untested).
3. New C# activity classes delivered as "drop-ins" (no server rebuild). `Elsa.DropIns` (elsa-extensions) watches a folder and loads assemblies at runtime (file watcher, 2 s debounce; `IDropIn.Install`; unloads on delete; NuGet and assembly catalogs). Full control of the node form. NOT verified: whether new nodes appear in Studio without a restart, whether unloading is clean, maturity (no README found). Security: anyone who can write to that folder runs code inside the Elsa server; needs review, signing and folder permissions.

## Versioning of code nodes
The `[Activity]` attribute has a `Version` (default 1; `RunPython` declares 1) and the registry can look a node up by type name and version. A changed shared code node could ship as a new version while old workflows keep the old one (my reading; not tested with two versions side by side).

## Organising nodes by project
- No project or folder concept found in the workflow management and labels modules (searched by class and property names only). Available grouping: node category (picker sections; settable per saved-workflow node), labels on workflows, tenants (isolation between organisations).
- Suggested (my reasoning): categories such as "Platform / Excel" and "Project X / ..." so a project's nodes are easy to find and promote.

## Implication: reusable nodes must not contain credentials (my reasoning)
A shared node such as "Portal X download" needs the portal login, mailbox and database credentials supplied by the CALLER. Studio has a secret picker input and Elsa has Secrets and Connections modules (research still to do). Design rule: credentials are inputs of the node (chosen from stored secrets), never hard-coded inside it.

## Working recommendation (my reasoning)
Two layers. Platform nodes: file tools plus DB, HTTP, Playwright, Graph, built and maintained centrally. Project nodes: built as saved workflows (way 1) or worker operations (way 2); when one proves reusable, promote it into the shared library with an owner, a version, a description, an example and a test. Way 3 (drop-in C#) only for nodes needing a custom form or in-process speed.
Governance questions for an organisation: who reviews a node before it is shared, how versions are retired, how a fix reaches workflows that pinned an old version.

## Open
- Who builds project nodes (Hope's team in Python only, or also .NET)?
- Whether Studio shows an upgrade prompt for pinned versions and how new versions are adopted in bulk: not checked in the UI.
- Whether drop-in nodes show up live: not tested.

## Language update (added 2026-09-30)
Answer to the first open question, from Hope: project nodes may be written in .NET, Python or JavaScript, the core runner must be .NET, and chained nodes in different languages must work seamlessly.
What follows for the three ways above (my reasoning):
- Way 1 (saved workflow as a node) is language-neutral: it only chains other nodes, so a project can compose Python, JavaScript and .NET steps with no code of its own.
- Way 2 (catalogue-driven nodes): "the Python worker" becomes "any worker". Each worker (Python, JavaScript, .NET) publishes a catalogue of its nodes in one shared format, and one small .NET provider turns all catalogues into Studio nodes, so Studio shows a single uniform list.
- Way 3 (drop-in C#): the security warning above matters more now. C# drop-ins run with the Elsa server's full access, including its secrets. A project team writing its own C# nodes should get a .NET WORKER process to load them in, the same isolation Python and JavaScript nodes get, and drop-ins loaded into the server itself should be limited to platform code reviewed centrally.
- Versioning and governance apply per node whatever its language; the shared node contract (research-14) is what a reviewer checks.
Each extra runtime (Python, Node, a .NET worker) is an approval, patching and monitoring cost for the organisation, so the day-one scope should stay small; current verdicts (research-19) need only .NET and Python.


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- Way 1 (saved workflow as a node) → a sub-workflow step that pins a version and shows "newer version available".
- Way 2 (catalogue-driven nodes) → auto-discovery from `activities/` and a configured extra folder. Workers in other languages can join later through the envelope.
- Way 3 (C# drop-ins) → not applicable. The equivalent is dropping a `.py` activity into the extra folder; it runs in worker processes, never in the control plane.
- Categories (for example `Platform / Excel`), activity versions and credentials-as-inputs apply. The governance questions (review, retirement, rollout of fixes) are still open.
