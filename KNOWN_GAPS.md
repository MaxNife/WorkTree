# KNOWN GAPS

Things that could not be verified in this environment, or that are deliberately faked. Each entry
says what is fake, what is real, and what remains to close it.

| # | Area | Gap | What exists instead | How to close |
|---|---|---|---|---|
| G1 | Repository | Withdrawn: this gap concerned a reference document that is no longer part of the project | not applicable | nothing to close |
| G2 | Oracle | never tested against a real Oracle instance; no Oracle-specific test yet | `python-oracledb` thin mode behind the `Database` interface; SQL activities exist and are type-checked but have not yet been run against SQLite or Oracle | add SQLite-backed activity tests, then point the activity `connection` at Oracle 19c+ |
| G3 | Microsoft Graph | never tested against a tenant | fake Graph server with token endpoint, `$filter`/`$orderby`, sendMail and upload; `email` and `graph_read_mail` use the same HTTP shapes | supply tenant id/client id/secret and mailbox scopes (Mail.Read, Mail.Send) |
| G4 | Portals | no real portal | fake portal server with API-token, form and form+email-OTP login, a file download and a session cookie | record real selectors and OTP sender in the activity inputs |
| G5 | SFTP | no SFTP server or activity test exists yet | `sftp` activity code is present and type-checked; no fixture exercises it | implement the planned paramiko fake server, then test against the organisation's SFTP host; LGPL ruling still needed (G10) |
| G6 | Vault | adapter is import-guarded and has no dedicated test yet | env + local JSON secret store used by the test suite; Vault adapter code exists | add a stub-client unit test, then `pip install 'uaf[vault]'`, set `UAF_SECRETS__ADAPTER=vault` + URL/token |
| G7 | RabbitMQ | adapter is import-guarded and not run against a broker | DB-backed bus with integration tests for enqueue, claim, ack, retry, dead-letter, lease redelivery, orphan release and concurrent claimers (`tests/integration/test_bus.py`) | `pip install 'uaf[rabbitmq]'`, set `UAF_BUS__ADAPTER=rabbitmq`, run the same tests against a broker |
| G8 | Playwright browsers | browser download not attempted; no browser activity test yet | `playwright_robot`/`playwright_script` code exists and type-checks against Playwright's Python API; fake portal exists | run `uv run playwright install chromium`, then test the robot against `fixtures.fake_services` |
| G9 | LibreOffice recalculation | not installed | option exists and is off by default | install LibreOffice and enable `recalculate` |
| G10 | Licensing | `paramiko` (LGPL) is used for SFTP; research notes require a legal ruling | isolated in one activity and the fixture; alternative is `asyncssh` (EPL) | legal decision |
| G11 | Email fallback | SMTP tested against a local sink only, Graph against the fake | both code paths exercised | configure a real SMTP relay |
| G12 | Frontend E2E | browser suite depends on Playwright browser availability | Vitest/component tests and API tests always run | run `npm run test:e2e` after `playwright install` |
| G13 | AI | `ai_extract` is off by default and tested only against a fake internal endpoint | configurable endpoint + JSON schema validation | AI framework approval, then set `UAF_AI__ENABLED=true` and the endpoint |
| G14 | High availability | no HA, single-node scheduler/worker pool | restart-safe durable state and resume | out of MVP scope per the spec |
| G15 | Audit on Oracle | `verify-audit` requires contiguous ids; an Oracle sequence can leave gaps after rollbacks, which would be reported as a broken chain. The `audit_head` row lock is verified on SQLite only | SQLite autoincrement ids are gap-free; the chain itself (prev_hash) is dialect-neutral | on Oracle, drop the id-contiguity check (keep prev_hash) or allocate ids under the `audit_head` lock |
