# Research 17: Secrets and credentials in Elsa

Status: research only, nothing built. Based on reading the elsa-core / elsa-extensions code (Elsa.Secrets, Elsa.Connections, Elsa.ExternalAuthentication, Studio secret picker, ROADMAP.md). Items marked UNVERIFIED were not tested. Updated 2026-09-29 with Hope's answers.

## Why this matters for us
Every project we described needs credentials: portal logins (form/token/MFA), Oracle connection strings, the Graph app registration, SMTP, network share access. Research 16 concluded that reusable project nodes should take credentials as *inputs* (picked from a stored list, like the "connection" dropdown in n8n / Make / Power Automate) and never hard-code them. So the question is what Elsa gives us to store and pick them.

## Hope's answers (2026-09-29) and what they mean

**1. Today: encrypted env vars + config.json files.**
- This fits `ConfigurationSecretStore` well (verified in code). In Elsa you create a secret whose only stored content is a *config key name*; the value is read from `IConfiguration` at run time, trying `Elsa:Secrets:<key>` first and then plain `<key>`. Elsa never stores the value itself. (Its "Write" just records the key name.)
- .NET configuration reads both env vars and JSON files, so your existing setup plugs in without changing where secrets live.
- One thing to pin down: who decrypts the "encrypted" env vars? If the platform/OS decrypts them before the process starts, Elsa just sees plain values and it works as is. If your own Python code decrypts them (app-level), Elsa cannot do that by itself and we would write a small custom `ISecretStore` (extension point, not a fork) that calls the same decrypt routine.
- Rotation with this store: change the env var / config value. JSON config files can be reloaded live if the file provider reloads on change; env vars generally need a process restart (standard .NET behaviour, UNVERIFIED in Elsa specifically).

**2. Graph auth = client secret keys.**
- A plain string secret, so it fits the secret picker and config store with no custom type. Simpler than certificates.
- Client secrets expire, so expiry is the practical rotation trigger even with no policy. Elsa's secret model has versions, but I did not see an expiry reminder or auto-rotation; that would be something we build or handle outside.

**3. No rotation policy yet, but keep in mind.**
- Design rule: nodes reference a secret by *name*, never by value. Then rotating means changing one place (the env var/config value or a new secret version) and every workflow using the name picks it up.
- Worst rotation case is the default encrypted store's static `EncryptionKey`: changing it breaks decryption of existing rows (no re-encrypt tool seen). The config-reference store avoids this, since there is nothing encrypted by Elsa.
- Not researched yet: whether a workflow running mid-rotation gets the old or new value (secret versions exist, resolution behaviour not tested).

**Leaning (not a decision, still researching):** config-reference store first, because it matches how the team already works and avoids Elsa's static-key weakness. Custom `ISecretStore` only if the env vars are decrypted at app level or the organisation later moves to a vault.

## What exists already (verified in code)

| Piece | What it does |
|---|---|
| `Elsa.Secrets` module | Stores named secrets with a type, versions, tenant scoping and permissions. Secrets can be referenced from workflows through a secret expression (`SecretExpressionHandler`). |
| `ISecretStore` | The storage contract. Pluggable. |
| `EncryptedSecretStore` | Default store: AES-GCM encryption of the secret value, saved through a repository. Default repository is a JSON file (`App_Data/elsa-secrets.json`); there is also an EF Core repository (EF Core has an Oracle provider, so Oracle persistence is plausible, UNVERIFIED end to end). |
| `ConfigurationSecretStore` | Stores only a config key name; resolves the value from `IConfiguration` (env vars, JSON files, anything plugged into .NET configuration). Bridge to injected env vars or a vault the platform team surfaces as config. |
| `DefaultSecretValueProtector` / `DefaultSecretResolver` | Encrypt/decrypt and resolve at run time. |
| Studio secret picker (`SecretPickerHandler`) | A dropdown editor in Studio so a node input can be "pick a secret" rather than typed text. |
| `[Input(CanContainSecrets = true)]` | Flag on activity inputs (e.g. SQL connection string) marking the field as sensitive. |
| `Elsa.Connections` | Models for OAuth and API-key connections, bindings and use grants. Closest thing to the "connections" concept in Make/n8n. Covers OAuth / API key only. |
| `Elsa.ExternalAuthentication` | OIDC broker (log in to external identity providers). Not needed for our first two projects. |

## Weak spots / things to be careful about

1. **Encryption key is a static value in options** (`SecretsOptions.EncryptionKey`). Whoever can read the app config can decrypt every stored secret, and rotating the key means re-encrypting existing rows (no built-in tooling seen). Only applies if we use the default encrypted store.
2. **No vault store built in.** No HashiCorp / Azure Key Vault / CyberArk store ships. Options: implement `ISecretStore` ourselves, or use `ConfigurationSecretStore`.
3. **Log/output masking is unresolved.** Outputs are persisted in `ActivityExecutionRecord` depending on `LogPersistenceMode`. I did not find a guarantee that a resolved secret never lands in a persisted input/output or a log line. Needs a real test before we trust it. UNVERIFIED.
4. **Modules are still maturing.** Secrets shipped as stable in 3.8.0 but ROADMAP.md still lists productization items as open.
5. **Open security assessment.** `doc/security-assessment/elsa-workflows-elsa-core-findings-2026-05-20.md` lists HIGH-severity findings against release/3.7.0. I only read the first ~90 lines and have NOT checked whether 3.8.0 fixed them. Must be checked before this goes anywhere near production.
6. **Credential-like artifacts that are not "secrets":** Playwright `storageState` files (cookies/tokens) are credentials too and must live in locked storage, not in the shared per-run workspace (see research 02).
7. **Code-running activities** (`RunPython`, `RunCSharp`) are disabled by default via `AllowHostCodeExecution`. Anyone allowed to author a workflow with those could read whatever the host process can read, including config secrets. So who can author matters as much as where secrets are stored.

## How this fits the reusable-node design (research 16)
- A project node has a "Credential" input that uses the secret picker. The node never sees the storage location, only the resolved value at run time.
- Same node, different credential = reuse across projects (e.g. one "Portal login" node, different secret per portal).
- Worker side (the isolated Python worker): should receive the resolved secret only for the duration of one call, never write it to the shared run workspace.
- Portal logins that vary (form / token / MFA) can be one credential type per style, with fields for username, password, and (for email OTP) which mailbox to read via Graph.

## Classification
- Already exists: secret storage + picker, versions, tenant scoping, config-reference store, `CanContainSecrets` flag.
- Extension point: custom `ISecretStore` (vault or app-level decrypt), custom secret types, custom Studio editors.
- Possibly fork-level (only if tests fail): guaranteed masking of secrets in persisted execution data.

## Still open
1. Who decrypts the encrypted env vars today: the platform/OS before start, or app code at run time?
2. Who may author workflows that use code activities?
3. Is a vault expected eventually (so we keep the store swappable)?

## Tests to run later (not now)
- Does a resolved secret show up in persisted activity input/output, logs or Studio's execution view?
- Does the 3.8.0 release still have the HIGH findings?
- Can Oracle be the store for secrets (and workflows) through the EF Core provider?
- Does a config change (JSON reload / env var) reach a running Elsa without restart?


## Python build update (2026-10-22)
Decision: the build is a Python/FastAPI MVP (`docs/BUILD_PROMPT_python_mvp.md`). Elsa is the major workflow reference and n8n a secondary reference for workflow behaviour and UX; neither is a dependency. How to read this note now:
- The Elsa Secrets modules are not used. The ideas carry over to our secret-store interface:
  - reference secrets by name;
  - config-reference store first (env vars + config file default);
  - no static encryption key;
  - a secret dropdown in the Studio;
  - sensitive-field flag and masking;
  - Playwright `storageState` treated as a credential;
  - only trusted users may author `run_python` / `legacy_robot_wrapper` steps.
- Masking is now our own requirement, tested by the A6 secrets grep (`BUILD_PROMPT:113`).
- Still open: who decrypts today's encrypted env vars; whether a vault is coming (an optional Vault adapter is specified).
