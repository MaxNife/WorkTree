# Activity catalogue

Generated from the activity classes by `scripts/gen_activity_docs.py`; do not edit by
hand. Drop-in activities from the configured extra folder appear in the Studio palette
and `uaf list-activities` but not here. How to write one: `docs/WRITING_AN_ACTIVITY.md`.

| Activity | Category | Version | Description |
|---|---|---|---|
| [`ai_extract`](#ai-extract) | Platform / AI | 1.0 | Optional OpenAI-compatible JSON extraction; disabled unless AI is configured. |
| [`csv`](#csv) | Platform / Files | 1.0 | Stream or chunk CSV files; tables leave as Parquet references. |
| [`download_file`](#download-file) | Platform / Integration | 1.0 | Stream a file into the run workspace with size and checksum verification. |
| [`echo`](#echo) | Platform / Core | 1.0 | Return the supplied inputs unchanged. |
| [`email`](#email) | Platform / Messaging | 1.0 | Send mail through Microsoft Graph client-secret auth or SMTP fallback. |
| [`excel`](#excel) | Platform / Excel | 1.0 | Read with calamine, edit with openpyxl, write with XlsxWriter. |
| [`fail`](#fail) | Platform / Core | 1.0 | Return the failed outcome with a message (testing error routes). |
| [`gl_query`](#gl-query) | Data / SQL | 1.0 | Run a parameterised SELECT against the GL database and write a table file. |
| [`graph_read_mail`](#graph-read-mail) | Platform / Messaging | 1.0 | Read the newest messages for a mailbox and optionally extract a code. |
| [`http_request`](#http-request) | Platform / Integration | 1.0 | Call an internal HTTP endpoint with an explicit timeout and response cap. |
| [`human_task`](#human-task) | Platform / Human | 1.0 | Suspend the run and wait for an approval, exception or manual match decision. |
| [`legacy_robot_wrapper`](#legacy-robot-wrapper) | Platform / Automation | 1.0 | Run an existing command-line robot without a shell, with timeouts and logs. |
| [`matching`](#matching) | Data / Matching | 1.0 | Deterministic fuzzy match two tables and write matched and unmatched rows. |
| [`oracle_bulk_load`](#oracle-bulk-load) | Data / Oracle | 1.0 | Chunked executemany into staging, then a MERGE into the target, with per-row errors. |
| [`oracle_execute`](#oracle-execute) | Data / Oracle | 1.0 | Execute a parameterised INSERT/UPDATE/DELETE or PL/SQL block. |
| [`oracle_query`](#oracle-query) | Data / Oracle | 1.0 | Parameterised Oracle query (python-oracledb thin mode or SQLite in tests). |
| [`playwright_robot`](#playwright-robot) | Platform / Browser | 1.0 | Run a browser robot from a declarative step list (portal login, download, extract). |
| [`playwright_script`](#playwright-script) | Platform / Browser | 1.0 | Run an existing Playwright Python script with page/context injected. |
| [`run_python`](#run-python) | Platform / Automation | 1.0 | Run a Python script in the isolated activity process with a workspace sandbox. |
| [`sftp`](#sftp) | Platform / Integration | 1.0 | SFTP get/put/list using paramiko. |
| [`sleep`](#sleep) | Platform / Core | 1.0 | Wait for a number of seconds (testing and pacing). |
| [`txt_log`](#txt-log) | Platform / Files | 1.0 | Append or read a plain-text log with a line cap. |
| [`unc_archive`](#unc-archive) | Platform / Files | 1.0 | Copy or move a file to a UNC/network path and verify its SHA-256. |
| [`zip`](#zip) | Platform / Files | 1.0 | AES ZIP create/extract with zip-slip and size protections. |

## ai_extract

Optional OpenAI-compatible JSON extraction; disabled unless AI is configured.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `text` | string |  |  |
| `file_path` | string |  |  |
| `instruction` | string | `'Extract the requested fields as JSON.'` |  |
| `fields` | array |  |  |
| `output_path` | string | `'ai-extract.json'` |  |
| `max_input_chars` | integer | `200000` |  |
| `model` | string | `'gpt-4o-mini'` |  |

## csv

Stream or chunk CSV files; tables leave as Parquet references.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `read` \| `write` \| `append` | `'read'` |  |
| `path` | string | `'data.csv'` |  |
| `source_path` | string or null | `None` |  |
| `output_path` | string or null | `None` |  |
| `encoding` | string | `'utf-8'` |  |
| `delimiter` | string | `','` |  |
| `output_format` | `parquet` \| `csv` \| `json` | `'parquet'` |  |
| `max_rows` | integer | `100000` |  |
| `rows` | array |  |  |

Fields by operation:

- `read`: `path`, `encoding`, `delimiter`, `output_path`, `output_format`, `max_rows`
- `write`: `path`, `encoding`, `rows`, `source_path`
- `append`: `path`, `encoding`, `rows`, `source_path`

## download_file

Stream a file into the run workspace with size and checksum verification.

| Input | Type | Default | Notes |
|---|---|---|---|
| `url` | string |  | required |
| `path` | string | `'download.bin'` |  |
| `headers` | object |  |  |
| `bearer_token` | string |  | sensitive (redacted in run records) |
| `timeout_seconds` | number | `60` |  |
| `expected_sha256` | string |  |  |
| `max_bytes` | integer | `2000000000` |  |

## echo

Return the supplied inputs unchanged.

| Input | Type | Default | Notes |
|---|---|---|---|
| `message` | string |  |  |

## email

Send mail through Microsoft Graph client-secret auth or SMTP fallback.

| Input | Type | Default | Notes |
|---|---|---|---|
| `provider` | `smtp` \| `graph` | `'smtp'` |  |
| `to` | array |  | required |
| `subject` | string |  | required |
| `body` | string |  |  |
| `html` | boolean | `False` |  |
| `attachments` | array |  |  |
| `smtp_host` | string | `'localhost'` |  |
| `smtp_port` | integer | `25` |  |
| `smtp_user` | string |  |  |
| `smtp_password` | string |  | sensitive (redacted in run records) |
| `smtp_from` | string | `'uaf@localhost'` |  |
| `tenant_id` | string |  |  |
| `client_id` | string |  |  |
| `client_secret` | string |  | sensitive (redacted in run records) |
| `sender` | string |  |  |
| `graph_base_url` | string | `'https://graph.microsoft.com/v1.0'` |  |
| `login_base_url` | string | `'https://login.microsoftonline.com'` |  |

## excel

Read with calamine, edit with openpyxl, write with XlsxWriter.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `read` \| `write` \| `set_cells` \| `sheets` | `'read'` |  |
| `path` | string | `'book.xlsx'` |  |
| `source_path` | string or null | `None` |  |
| `sheet` | string |  | options depend on other fields |
| `output_path` | string or null | `None` |  |
| `rows` | array |  |  |
| `cells` | object |  |  |
| `output_format` | `parquet` \| `csv` \| `json` | `'parquet'` |  |
| `max_rows` | integer | `100000` |  |

Fields by operation:

- `read`: `path`, `sheet`, `output_path`, `output_format`, `max_rows`
- `write`: `path`, `sheet`, `rows`, `source_path`
- `set_cells`: `path`, `sheet`, `cells`
- `sheets`: `path`

## fail

Return the failed outcome with a message (testing error routes).

| Input | Type | Default | Notes |
|---|---|---|---|
| `message` | string | `'failed intentionally'` |  |

## gl_query

Run a parameterised SELECT against the GL database and write a table file.

| Input | Type | Default | Notes |
|---|---|---|---|
| `db_url` | string | `'sqlite:///./runtime/gl.db'` |  |
| `sql` | string |  | required |
| `params` | object |  |  |
| `output_path` | string | `'query-result.parquet'` |  |
| `output_format` | `parquet` \| `csv` \| `json` | `'parquet'` |  |
| `max_rows` | integer | `100000` |  |

## graph_read_mail

Read the newest messages for a mailbox and optionally extract a code.

| Input | Type | Default | Notes |
|---|---|---|---|
| `tenant_id` | string |  | required |
| `client_id` | string |  | required |
| `client_secret` | string |  | required, sensitive (redacted in run records) |
| `mailbox` | string |  | required |
| `sender` | string |  |  |
| `since` | string |  |  |
| `top` | integer | `10` |  |
| `code_regex` | string |  |  |
| `graph_base_url` | string | `'https://graph.microsoft.com/v1.0'` |  |
| `login_base_url` | string | `'https://login.microsoftonline.com'` |  |

## http_request

Call an internal HTTP endpoint with an explicit timeout and response cap.

| Input | Type | Default | Notes |
|---|---|---|---|
| `method` | `GET` \| `POST` \| `PUT` \| `PATCH` \| `DELETE` | `'GET'` |  |
| `url` | string |  | required |
| `headers` | object |  |  |
| `params` | object |  |  |
| `json_body` | any | `None` |  |
| `body` | string or null | `None` |  |
| `bearer_token` | string |  | sensitive (redacted in run records) |
| `timeout_seconds` | number | `30` |  |
| `max_response_bytes` | integer | `2000000` |  |
| `output_path` | string or null | `None` |  |
| `expected_status` | array |  |  |

## human_task

Suspend the run and wait for an approval, exception or manual match decision.

| Input | Type | Default | Notes |
|---|---|---|---|
| `type` | `approval` \| `manual_match` \| `data_entry` \| `exception_disposition` | `'approval'` |  |
| `title` | string |  |  |
| `description` | string |  |  |
| `assignee_role` | string | `'operator'` |  |
| `priority` | integer | `2` |  |
| `due_minutes` | integer | `60` |  |
| `payload` | object |  |  |

## legacy_robot_wrapper

Run an existing command-line robot without a shell, with timeouts and logs.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `executable` | string | `'python'` |  |
| `args` | array |  |  |
| `working_dir` | string | `'.'` |  |
| `timeout_seconds` | integer | `120` |  |
| `output_path` | string | `'legacy-output.txt'` |  |
| `input_text` | string |  |  |

## matching

Deterministic fuzzy match two tables and write matched and unmatched rows.

| Input | Type | Default | Notes |
|---|---|---|---|
| `left_path` | string |  | required |
| `right_path` | string |  | required |
| `left_key` | string |  | required |
| `right_key` | string |  | required |
| `threshold` | number | `0.85` |  |
| `limit` | integer | `100000` |  |
| `output_path` | string | `'matches.parquet'` |  |

## oracle_bulk_load

Chunked executemany into staging, then a MERGE into the target, with per-row errors.

| Input | Type | Default | Notes |
|---|---|---|---|
| `db_url` | string | `'sqlite:///./runtime/gl.db'` |  |
| `source_path` | string |  | required |
| `table` | string |  | required |
| `staging_table` | string or null | `None` |  |
| `columns` | array |  |  |
| `key_columns` | array |  |  |
| `chunk_size` | integer | `1000` |  |
| `clear_staging` | boolean | `True` |  |

## oracle_execute

Execute a parameterised INSERT/UPDATE/DELETE or PL/SQL block.

| Input | Type | Default | Notes |
|---|---|---|---|
| `db_url` | string | `'sqlite:///./runtime/gl.db'` |  |
| `sql` | string |  | required |
| `params` | object or array |  |  |
| `chunk_size` | integer | `1000` |  |

## oracle_query

Parameterised Oracle query (python-oracledb thin mode or SQLite in tests).

| Input | Type | Default | Notes |
|---|---|---|---|
| `db_url` | string | `'sqlite:///./runtime/gl.db'` |  |
| `sql` | string |  | required |
| `params` | object |  |  |
| `output_path` | string | `'query-result.parquet'` |  |
| `output_format` | `parquet` \| `csv` \| `json` | `'parquet'` |  |
| `max_rows` | integer | `100000` |  |

## playwright_robot

Run a browser robot from a declarative step list (portal login, download, extract).

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `browser` | `chromium` \| `firefox` \| `webkit` | `'chromium'` |  |
| `headless` | boolean | `True` |  |
| `base_url` | string |  |  |
| `start_url` | string |  |  |
| `steps` | array |  |  |
| `username` | string |  |  |
| `password` | string |  | sensitive (redacted in run records) |
| `otp` | string |  | sensitive (redacted in run records) |
| `screenshot_path` | string | `'page.png'` |  |
| `screenshot_on_failure` | boolean | `True` |  |
| `timeout_ms` | integer | `30000` |  |

## playwright_script

Run an existing Playwright Python script with page/context injected.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `script_path` | string |  |  |
| `script` | string |  |  |
| `browser` | `chromium` \| `firefox` \| `webkit` | `'chromium'` |  |
| `headless` | boolean | `True` |  |
| `start_url` | string |  |  |
| `output_path` | string | `'script-result.json'` |  |
| `screenshot_path` | string | `'script.png'` |  |

## run_python

Run a Python script in the isolated activity process with a workspace sandbox.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `script` | string |  |  |
| `script_path` | string |  |  |
| `args` | array |  |  |
| `timeout_seconds` | integer | `120` |  |
| `result_path` | string | `'script-result.json'` |  |
| `output_path` | string | `'script-output.txt'` |  |

## sftp

SFTP get/put/list using paramiko.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `get` \| `put` \| `list` | `'get'` |  |
| `host` | string |  | required |
| `port` | integer | `22` |  |
| `username` | string |  | required |
| `password` | string |  | sensitive (redacted in run records) |
| `private_key_path` | string |  |  |
| `known_hosts_path` | string |  |  |
| `remote_path` | string | `'.'` |  |
| `local_path` | string |  |  |
| `timeout_seconds` | number | `30` |  |

## sleep

Wait for a number of seconds (testing and pacing).

| Input | Type | Default | Notes |
|---|---|---|---|
| `seconds` | number | `1` |  |

## txt_log

Append or read a plain-text log with a line cap.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `read` \| `append` \| `write` | `'append'` |  |
| `path` | string | `'run.log'` |  |
| `text` | string |  |  |
| `lines` | array |  |  |
| `max_lines` | integer | `10000` |  |

Fields by operation:

- `read`: `path`, `max_lines`
- `append`: `path`, `text`, `lines`
- `write`: `path`, `text`, `lines`

## unc_archive

Copy or move a file to a UNC/network path and verify its SHA-256.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `copy` \| `move` | `'copy'` |  |
| `source_path` | string |  | required |
| `destination_dir` | string |  | required |
| `filename` | string |  |  |
| `expected_sha256` | string |  |  |
| `overwrite` | boolean | `False` |  |

## zip

AES ZIP create/extract with zip-slip and size protections.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `extract` \| `list` \| `create` | `'extract'` |  |
| `path` | string | `'archive.zip'` |  |
| `output_dir` | string | `'extracted'` |  |
| `password` | string |  | sensitive (redacted in run records) |
| `files` | array |  |  |
| `max_total_bytes` | integer | `1000000000` |  |

Fields by operation:

- `extract`: `path`, `output_dir`, `password`, `max_total_bytes`
- `list`: `path`, `password`
- `create`: `path`, `files`, `password`
