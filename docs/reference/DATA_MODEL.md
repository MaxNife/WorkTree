# Data model

Generated from `app/adapters/db/models.py` by `scripts/gen_data_model.py`; do not edit by hand.
The Alembic migrations in `app/adapters/db/migrations/versions/` create exactly this schema
(`alembic check` reports no differences; `tests/integration/test_database.py` enforces it).

## Dialect notes (SQLite default, Oracle option)

- **Identifiers:** UUID hex strings (`String(32)`) for most keys, so no sequences are needed;
  `audit_log.id`, `bus_jobs.id` and `roles.id` are integer identities (Oracle 12c+ `GENERATED
  ... AS IDENTITY`).
- **JSON:** SQLAlchemy `JSON` maps to SQLite `JSON` (text) and Oracle 21c `JSON`; on 19c it is
  stored as `CLOB` with an `IS JSON` check. Values are always small: bulk data travels as
  workspace files (rule "files by reference").
- **Booleans:** SQLite `INTEGER 0/1`; Oracle 23ai `BOOLEAN`, earlier `NUMBER(1)`.
- **Timestamps:** `UTCDateTime` stores naive UTC and returns timezone-aware UTC on every backend.
- **`RETURNING`:** the bus claim uses `UPDATE ... RETURNING` on SQLite; other dialects use
  `SELECT ... FOR UPDATE SKIP LOCKED` (`app/bus/db_bus.py`).
- **Append-only audit:** `audit_log` is never updated or deleted (ORM guard + tests). Each
  append first updates the single `audit_head` row, serialising chain appends.
- **Oracle connection:** `oracle+oracledb://user@host:1521/?service_name=...` (python-oracledb
  thin mode, no Instant Client); the password comes from the environment, never `config.yaml`.

## Tables

### `artifacts`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | no | FK → `runs.id` |
| `step_id` | VARCHAR(100) | no |  |
| `name` | VARCHAR(255) | no |  |
| `path` | VARCHAR(1000) | no |  |
| `sha256` | VARCHAR(64) | no |  |
| `bytes` | BIGINT | no |  |
| `created_at` | DATETIME | no |  |

- index `ix_artifacts_run` (run_id)

### `audit_head`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `appends` | BIGINT | no |  |

### `audit_log`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `ts` | DATETIME | no |  |
| `actor` | VARCHAR(100) | no |  |
| `action` | VARCHAR(100) | no |  |
| `resource_type` | VARCHAR(50) | no |  |
| `resource_id` | VARCHAR(100) | no |  |
| `source_ip` | VARCHAR(64) | no |  |
| `before` | JSON | yes |  |
| `after` | JSON | yes |  |
| `correlation_id` | VARCHAR(64) | no |  |
| `prev_hash` | VARCHAR(64) | no |  |
| `hash` | VARCHAR(64) | no |  |

- index `ix_audit_resource` (resource_type, resource_id)
- index `ix_audit_ts` (ts)

### `bus_jobs`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `queue` | VARCHAR(100) | no |  |
| `payload` | JSON | no |  |
| `state` | VARCHAR(20) | no |  |
| `attempts` | INTEGER | no |  |
| `max_attempts` | INTEGER | no |  |
| `visible_at` | DATETIME | no |  |
| `claimed_by` | VARCHAR(100) | yes |  |
| `claimed_at` | DATETIME | yes |  |
| `last_error` | TEXT | no |  |
| `result` | JSON | yes |  |
| `created_at` | DATETIME | no |  |
| `finished_at` | DATETIME | yes |  |

- index `ix_bus_claim` (queue, state, visible_at)

### `comments`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `resource_type` | VARCHAR(20) | no |  |
| `resource_id` | VARCHAR(100) | no |  |
| `user_id` | VARCHAR(32) | no |  |
| `author` | VARCHAR(100) | no |  |
| `body` | TEXT | no |  |
| `created_at` | DATETIME | no |  |

- index `ix_comments_resource` (resource_type, resource_id, created_at)

### `environments`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `name` | VARCHAR(20) | no | unique |
| `is_production` | BOOLEAN | no |  |

### `idempotency_keys`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `key` | VARCHAR(200) | no | PK |
| `user_id` | VARCHAR(32) | no |  |
| `endpoint` | VARCHAR(200) | no |  |
| `request_hash` | VARCHAR(64) | no |  |
| `response` | JSON | yes |  |
| `status_code` | INTEGER | no |  |
| `created_at` | DATETIME | no |  |
| `expires_at` | DATETIME | yes |  |

### `incidents`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | no | FK → `runs.id` |
| `step_id` | VARCHAR(100) | yes |  |
| `kind` | VARCHAR(50) | no |  |
| `message` | TEXT | no |  |
| `resolved` | BOOLEAN | no |  |
| `created_at` | DATETIME | no |  |

### `notifications`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `user_id` | VARCHAR(32) | yes |  |
| `role` | VARCHAR(40) | yes |  |
| `title` | VARCHAR(255) | no |  |
| `body` | TEXT | no |  |
| `kind` | VARCHAR(40) | no |  |
| `link` | VARCHAR(500) | no |  |
| `read` | BOOLEAN | no |  |
| `created_at` | DATETIME | no |  |

- index `ix_notifications_read` (read, created_at)

### `processed_files`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `schedule_id` | VARCHAR(32) | no |  |
| `path` | VARCHAR(1000) | no |  |
| `sha256` | VARCHAR(64) | no |  |
| `processed_at` | DATETIME | no |  |

- unique `uq_processed_file` (schedule_id, path, sha256)

### `promotions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `workflow_id` | VARCHAR(32) | no | FK → `workflows.id` |
| `version_id` | VARCHAR(32) | no | FK → `workflow_versions.id` |
| `version` | INTEGER | no |  |
| `from_environment` | VARCHAR(20) | no |  |
| `to_environment` | VARCHAR(20) | no |  |
| `status` | VARCHAR(20) | no |  |
| `requested_by` | VARCHAR(32) | no |  |
| `decided_by` | VARCHAR(32) | yes |  |
| `reason` | TEXT | no |  |
| `requested_at` | DATETIME | no |  |
| `decided_at` | DATETIME | yes |  |

- index `ix_promotions_workflow_env` (workflow_id, to_environment)

### `resume_tokens`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | no | FK → `runs.id` |
| `step_id` | VARCHAR(100) | no |  |
| `token` | VARCHAR(64) | no | unique |
| `payload` | JSON | no |  |
| `created_at` | DATETIME | no |  |
| `consumed_at` | DATETIME | yes |  |

### `roles`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `name` | VARCHAR(50) | no | unique |
| `description` | VARCHAR(255) | no |  |

### `run_steps`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | no | FK → `runs.id` |
| `step_id` | VARCHAR(100) | no |  |
| `activity` | VARCHAR(100) | no |  |
| `iteration` | INTEGER | no |  |
| `state` | VARCHAR(20) | no |  |
| `outcome` | VARCHAR(20) | yes |  |
| `attempt` | INTEGER | no |  |
| `inputs` | JSON | no |  |
| `outputs` | JSON | no |  |
| `message` | TEXT | no |  |
| `artifacts` | JSON | no |  |
| `error_code` | VARCHAR(100) | no |  |
| `started_at` | DATETIME | yes |  |
| `finished_at` | DATETIME | yes |  |
| `next_attempt_at` | DATETIME | yes |  |
| `child_run_id` | VARCHAR(32) | yes |  |
| `foreach_count` | INTEGER | no |  |
| `duration_ms` | INTEGER | no |  |
| `bus_job_id` | INTEGER | yes |  |

- index `ix_run_steps_run` (run_id, step_id)
- index `ix_run_steps_state` (state)
- unique `uq_run_step_iteration` (run_id, step_id, iteration)

### `runs`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `workflow_id` | VARCHAR(32) | no |  |
| `workflow_name` | VARCHAR(200) | no |  |
| `version_id` | VARCHAR(32) | no |  |
| `version` | INTEGER | no |  |
| `environment` | VARCHAR(20) | no |  |
| `status` | VARCHAR(20) | no |  |
| `trigger` | VARCHAR(20) | no |  |
| `trigger_detail` | JSON | no |  |
| `correlation_id` | VARCHAR(64) | no |  |
| `workspace` | VARCHAR(500) | no |  |
| `current_step` | VARCHAR(100) | yes |  |
| `inputs` | JSON | no |  |
| `outputs` | JSON | no |  |
| `error` | TEXT | no |  |
| `requested_by` | VARCHAR(32) | no |  |
| `duplicate_key` | VARCHAR(200) | no |  |
| `parent_run_id` | VARCHAR(32) | yes |  |
| `dependency_dispatched` | BOOLEAN | no |  |
| `created_at` | DATETIME | no |  |
| `started_at` | DATETIME | yes |  |
| `finished_at` | DATETIME | yes |  |
| `updated_at` | DATETIME | no |  |

- index `ix_runs_created` (created_at)
- index `ix_runs_duplicate` (workflow_id, duplicate_key, status)
- index `ix_runs_status_started` (status, started_at)
- index `ix_runs_workflow_created` (workflow_id, created_at)

### `saved_views`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `user_id` | VARCHAR(32) | no |  |
| `resource` | VARCHAR(40) | no |  |
| `name` | VARCHAR(100) | no |  |
| `query` | JSON | no |  |
| `shared` | BOOLEAN | no |  |
| `created_at` | DATETIME | no |  |

- unique `uq_saved_view_name` (user_id, resource, name)

### `schedules`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `workflow_id` | VARCHAR(32) | no | FK → `workflows.id` |
| `kind` | VARCHAR(20) | no |  |
| `name` | VARCHAR(200) | no |  |
| `cron` | VARCHAR(100) | no |  |
| `timezone` | VARCHAR(64) | no |  |
| `enabled` | BOOLEAN | no |  |
| `config` | JSON | no |  |
| `token` | VARCHAR(128) | yes | unique |
| `environment` | VARCHAR(20) | no |  |
| `next_run_at` | DATETIME | yes |  |
| `last_run_at` | DATETIME | yes |  |
| `created_by` | VARCHAR(32) | no |  |
| `created_at` | DATETIME | no |  |

- index `ix_schedules_enabled` (enabled, kind)

### `secrets_metadata`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `name` | VARCHAR(200) | no | PK |
| `description` | VARCHAR(255) | no |  |
| `last_rotated_at` | DATETIME | yes |  |
| `created_at` | DATETIME | no |  |

### `sessions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `user_id` | VARCHAR(32) | no | FK → `users.id` |
| `csrf_token` | VARCHAR(64) | no |  |
| `created_at` | DATETIME | no |  |
| `expires_at` | DATETIME | no |  |
| `revoked_at` | DATETIME | yes |  |
| `source_ip` | VARCHAR(64) | no |  |
| `user_agent` | VARCHAR(255) | no |  |

### `step_attempts`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | no |  |
| `step_id` | VARCHAR(100) | no |  |
| `iteration` | INTEGER | no |  |
| `attempt` | INTEGER | no |  |
| `outcome` | VARCHAR(20) | no |  |
| `message` | TEXT | no |  |
| `started_at` | DATETIME | no |  |
| `finished_at` | DATETIME | yes |  |
| `duration_ms` | INTEGER | no |  |

- index `ix_step_attempts_run` (run_id, step_id)

### `task_events`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `task_id` | VARCHAR(32) | no | FK → `tasks.id` |
| `user_id` | VARCHAR(32) | yes |  |
| `action` | VARCHAR(40) | no |  |
| `payload` | JSON | no |  |
| `created_at` | DATETIME | no |  |

### `tasks`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `run_id` | VARCHAR(32) | yes |  |
| `step_id` | VARCHAR(100) | yes |  |
| `type` | VARCHAR(40) | no |  |
| `title` | VARCHAR(255) | no |  |
| `description` | TEXT | no |  |
| `assignee_role` | VARCHAR(40) | no |  |
| `status` | VARCHAR(20) | no |  |
| `priority` | INTEGER | no |  |
| `payload` | JSON | no |  |
| `result` | JSON | no |  |
| `claimed_by` | VARCHAR(32) | yes |  |
| `decision` | VARCHAR(40) | no |  |
| `reason` | TEXT | no |  |
| `due_at` | DATETIME | yes |  |
| `created_at` | DATETIME | no |  |
| `claimed_at` | DATETIME | yes |  |
| `completed_at` | DATETIME | yes |  |

- index `ix_tasks_due` (status, due_at)
- index `ix_tasks_run` (run_id)
- index `ix_tasks_status_role` (status, assignee_role)

### `user_roles`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `user_id` | VARCHAR(32) | no | PK, FK → `users.id` |
| `role_id` | INTEGER | no | PK, FK → `roles.id` |

### `users`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `username` | VARCHAR(100) | no | unique |
| `display_name` | VARCHAR(200) | no |  |
| `password_hash` | VARCHAR(255) | no |  |
| `is_active` | BOOLEAN | no |  |
| `must_change_password` | BOOLEAN | no |  |
| `created_at` | DATETIME | no |  |
| `last_login_at` | DATETIME | yes |  |

### `workflow_versions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `workflow_id` | VARCHAR(32) | no | FK → `workflows.id` |
| `version` | INTEGER | no |  |
| `definition` | JSON | no |  |
| `checksum` | VARCHAR(64) | no |  |
| `created_by` | VARCHAR(32) | no |  |
| `created_at` | DATETIME | no |  |
| `activity_versions` | JSON | no |  |

- index `ix_workflow_versions_workflow` (workflow_id, version)
- unique `uq_workflow_version` (workflow_id, version)

### `workflows`

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | VARCHAR(32) | no | PK |
| `name` | VARCHAR(200) | no | unique |
| `description` | TEXT | no |  |
| `owner` | VARCHAR(100) | no |  |
| `folder` | VARCHAR(200) | no |  |
| `tags` | JSON | no |  |
| `notes` | TEXT | no |  |
| `archived` | BOOLEAN | no |  |
| `latest_version` | INTEGER | no |  |
| `created_by` | VARCHAR(32) | no |  |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |
