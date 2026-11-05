# ADR 0001: Bind secrets to where and how they are used

Status: accepted, 2026-11-05. Addresses SEC-10 in `docs/SECURITY.md`.

## Problem

Any Author can name any secret in a workflow and send it to any host. Masking does not help: it
protects logs and API responses, not what an activity sends over the network or writes to a file.

An Author can move a secret out in three ways:

1. **Through a credential field**, such as `bearer_token` on an `http_request` to a host they
   control.
2. **Through any other field**, such as an email body, a request body or a log file. No credential
   field is involved, so a rule about destinations alone would miss it.
3. **Through a trusted host**, by using a powerful credential against the real service. This is
   misuse of access, not theft of the value.

A related gap is server-side request forgery: `validate_url` checks only the scheme, so a step can
reach loopback addresses and cloud metadata endpoints, with or without a secret.

## Decision

Four rules. All are enforced on the server and refuse by default.

### Rule 1: placement

A non-Admin may reference a secret only in an activity's declared credential inputs. Everything
else is refused when a workflow is saved and when a step is test-run, so a secret cannot be put in
a body, a message or a file.

Activities declare `credential_inputs`, which adds to `sensitive_fields`. `http_request` and
`download_file` add `headers`. `secret_only_inputs` from SEC-1 are also credential inputs.

### Rule 2: destination

Each secret has an Admin-managed `allowed_hosts` list of exact hosts and `*.example.com` patterns.
A step that uses a secret on an activity with a network destination runs only if every destination
host matches every secret the step uses.

Activities declare `destination_inputs`, such as `url` or `host`. The check runs at dispatch on the
resolved inputs, because a destination can come from step data, and it applies whoever wrote the
workflow. An empty list refuses. A destination that cannot be parsed refuses. Redirects are not a
way around this because `http_request` and `download_file` do not follow them.

### Rule 3: environment

Each secret has an Admin-managed `environments` list, and a new secret defaults to `dev` only. A
step uses a secret only if the run's environment is listed. "Run this step" counts as `dev`.

This is what makes Rule 2 enough without per-workflow grants. `test` and `prod` run only versions
that passed promotion, and an Author cannot approve their own. So a production credential can only
be reached through a version that an Approver reviewed.

Approvers must be able to see what they are approving, so a promotion request records the secrets
the version uses and their allowed hosts, and the API returns them.

### Rule 4: network egress

`validate_url` refuses addresses in `activities.egress_denied_networks`, which defaults to loopback
and link-local ranges, including the cloud metadata address. Private ranges stay allowed because
internal portals and databases are the normal case here. Hostnames are resolved and every returned
address is checked.

## Alternatives rejected

- **Per-workflow or per-author grants alone.** They do not stop exfiltration: an Author with access
  to a workflow can add a step to it. They also add Admin work for every workflow. Rules 2 and 3
  give more protection for less work.
- **Masking outbound traffic.** It would corrupt the real credentials activities must send.
- **Host filtering alone.** It misses a secret written into an email body or a file. Rule 1 exists
  for this.
- **Blocking all private addresses.** It would block the internal systems this product automates.

## Consequences

- An Admin must set `allowed_hosts` and `environments` before a secret works outside its defaults.
  Secrets used only in local activities, such as an archive password, need `environments` only.
- Empty policies refuse, so nothing silently stays open after the upgrade. Existing secrets stop
  working until an Admin sets their policy. The error names the secret and the setting.
- `secrets.enforce_policy` turns rules 2 and 3 off for local development and most tests. The
  application refuses to start in `prod` with it off, as it does for an insecure session cookie.
- Authors can no longer put a secret in a URL query string or a body. An Admin can, because Admin
  is already trusted with `run_python`.

## Remaining risk

- An Author can still misuse a `dev` credential against its allowed host. Keep `dev` credentials
  low in value.
- An Approver can approve a bad version. Promotion shows them what is used; judgement is theirs.
- Admins are trusted, and Rule 1 does not apply to them.
- DNS can change between the egress check and the connection. Rule 2 still holds, because it
  compares hostnames, but Rule 4 can be bypassed this way.
- Playwright robots can navigate inside a script after the check. They are Admin-only, so this
  falls under the same trust.
