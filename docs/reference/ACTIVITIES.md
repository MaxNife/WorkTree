# Activity catalogue

Generated from the activity classes by `scripts/gen_activity_docs.py`; do not edit by
hand. Drop-in activities from the configured extra folder appear in the Studio palette
and `uaf list-activities` but not here. How to write one: `docs/reference/WRITING_AN_ACTIVITY.md`.

| Activity | Category | Version | Description |
|---|---|---|---|
| [`ai_extract`](#ai-extract) | Platform / AI | 1.0 | Extract a JSON object that must match a JSON schema, via the configured internal OpenAI-compatible endpoint. Off by default; pending AI-framework approval. |
| [`csv`](#csv) | Platform / Files | 1.0 | Stream or chunk CSV and fixed-width files; tables leave as Parquet references. |
| [`document`](#document) | Platform / Documents | 1.0 | Word documents (.docx): convert to txt, md or html, extract text, info, and mail merge from CSV/Excel or rows; confined to the run workspace. |
| [`download_file`](#download-file) | Platform / Integration | 1.0 | Stream a file into the run workspace with size and checksum verification. |
| [`echo`](#echo) | Platform / Core | 1.0 | Return the supplied inputs unchanged. |
| [`email`](#email) | Platform / Messaging | 1.0 | Send mail through Microsoft Graph client-secret auth or SMTP fallback. |
| [`excel`](#excel) | Platform / Excel | 1.0 | Read with calamine, edit with openpyxl, write with XlsxWriter. |
| [`fail`](#fail) | Platform / Core | 1.0 | Return the failed outcome with a message (testing error routes). |
| [`gl_query`](#gl-query) | Data / SQL | 1.0 | Run a parameterised SELECT against the GL database and write a table file. |
| [`graph_read_mail`](#graph-read-mail) | Platform / Messaging | 1.0 | Read the newest messages for a mailbox and optionally extract a code. |
| [`http_request`](#http-request) | Platform / Integration | 1.0 | Call an internal HTTP endpoint with an explicit timeout and response cap. |
| [`human_task`](#human-task) | Platform / Human | 1.0 | Suspend the run and wait for an approval, exception or manual match decision. |
| [`legacy_robot_wrapper`](#legacy-robot-wrapper) | Platform / Automation | 1.0 | Run an existing command-line robot without a shell: env from inputs, exit-code mapping, masked logs, and named output files collected as artifacts. |
| [`matching`](#matching) | Data / Matching | 1.0 | Reconcile two tables on a key with optional amount/date tolerance, 1:1 or 1:N; writes matched, unmatched-A and unmatched-B tables. |
| [`oracle_bulk_load`](#oracle-bulk-load) | Data / Oracle | 1.0 | Chunked executemany into staging, then a MERGE into the target, with per-row errors. |
| [`oracle_execute`](#oracle-execute) | Data / Oracle | 1.0 | Execute a parameterised INSERT/UPDATE/DELETE or PL/SQL block. |
| [`oracle_query`](#oracle-query) | Data / Oracle | 1.0 | Parameterised Oracle query (python-oracledb thin mode or SQLite in tests). |
| [`pdf`](#pdf) | Platform / Documents | 1.0 | PDF info, text, combine, extract pages, split, protect (AES-256), watermark, form fill and optimize; confined to the run workspace. |
| [`playwright_robot`](#playwright-robot) | Platform / Browser | 1.0 | Run a browser robot from a declarative step list, with API-token, form or form+email-OTP login and reusable per-portal sessions. |
| [`playwright_script`](#playwright-script) | Platform / Browser | 1.0 | Run an existing Playwright Python script with page/context injected. |
| [`run_python`](#run-python) | Platform / Automation | 1.0 | Run a Python script in its own process with the run workspace as its folder (process isolation, not a sandbox; Admin-only). |
| [`sftp`](#sftp) | Platform / Integration | 1.0 | SFTP get/put/list using paramiko. |
| [`sleep`](#sleep) | Platform / Core | 1.0 | Wait for a number of seconds (testing and pacing). |
| [`spreadsheet`](#spreadsheet) | Platform / Excel | 1.0 | Calculate workbooks with the pure-Python formula engine: recalculate formulas, fill a model's inputs and read its results, read computed ranges, evaluate, convert, check. |
| [`txt_log`](#txt-log) | Platform / Files | 1.0 | Append or read a plain-text log with a line cap. |
| [`unc_archive`](#unc-archive) | Platform / Files | 1.0 | Copy or move a file to a UNC/network path and verify its SHA-256. The destination must be inside a folder listed in the server's activities.archive_roots. |
| [`zip`](#zip) | Platform / Files | 1.0 | AES ZIP create/extract with zip-slip and size protections. |

## ai_extract

Extract a JSON object that must match a JSON schema, via the configured internal OpenAI-compatible endpoint. Off by default; pending AI-framework approval.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `text` | string |  |  |
| `file_path` | string |  |  |
| `instruction` | string | `'Extract the requested fields as JSON.'` |  |
| `json_schema` | object |  |  |
| `fields` | array |  |  |
| `output_path` | string | `'ai-extract.json'` |  |
| `max_input_chars` | integer | `200000` |  |
| `model` | string | `'gpt-4o-mini'` |  |
| `timeout_seconds` | number | `60` |  |

## csv

Stream or chunk CSV and fixed-width files; tables leave as Parquet references.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `read` \| `write` \| `append` \| `read_fwf` | `'read'` |  |
| `path` | string | `'data.csv'` |  |
| `source_path` | string or null | `None` |  |
| `output_path` | string or null | `None` |  |
| `encoding` | string | `'utf-8'` |  |
| `delimiter` | string | `','` |  |
| `widths` | array |  |  |
| `names` | array |  |  |
| `output_format` | `parquet` \| `csv` \| `json` | `'parquet'` |  |
| `max_rows` | integer | `100000` |  |
| `chunk_size` | integer | `50000` |  |
| `rows` | array |  |  |

Fields by operation:

- `read`: `path`, `encoding`, `delimiter`, `output_path`, `output_format`, `max_rows`, `chunk_size`
- `read_fwf`: `path`, `encoding`, `widths`, `names`, `output_path`, `output_format`, `max_rows`, `chunk_size`
- `write`: `path`, `encoding`, `rows`, `source_path`
- `append`: `path`, `encoding`, `rows`, `source_path`

## document

Word documents (.docx): convert to txt, md or html, extract text, info, and mail merge from CSV/Excel or rows; confined to the run workspace.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `convert` \| `text` \| `info` \| `mail_merge` | `'convert'` |  |
| `path` | string | `'document.docx'` |  |
| `output_path` | string |  |  |
| `data_path` | string |  |  |
| `rows` | array |  |  |
| `sheet` | string |  |  |

Fields by operation:

- `convert`: `path`, `output_path`
- `text`: `path`, `output_path`
- `info`: `path`
- `mail_merge`: `path`, `data_path`, `rows`, `sheet`, `output_path`

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
| `recalculate` | boolean | `False` |  |

Fields by operation:

- `read`: `path`, `sheet`, `output_path`, `output_format`, `max_rows`
- `write`: `path`, `sheet`, `rows`, `source_path`, `recalculate`
- `set_cells`: `path`, `sheet`, `cells`, `recalculate`
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
| `assignee_role` | Role | `'operator'` |  |
| `priority` | integer | `2` |  |
| `due_minutes` | integer | `60` |  |
| `payload` | object |  |  |

## legacy_robot_wrapper

Run an existing command-line robot without a shell: env from inputs, exit-code mapping, masked logs, and named output files collected as artifacts.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `executable` | string | `'python'` |  |
| `args` | array |  |  |
| `env` | object |  |  |
| `working_dir` | string | `'.'` |  |
| `timeout_seconds` | integer | `120` |  |
| `output_path` | string | `'legacy-output.txt'` |  |
| `input_text` | string |  |  |
| `encoding` | string | `'utf-8'` |  |
| `success_codes` | array |  |  |
| `exit_code_messages` | object |  |  |
| `output_files` | array |  |  |
| `require_output_files` | boolean | `True` |  |

## matching

Reconcile two tables on a key with optional amount/date tolerance, 1:1 or 1:N; writes matched, unmatched-A and unmatched-B tables.

| Input | Type | Default | Notes |
|---|---|---|---|
| `left_key` | string |  | required |
| `right_key` | string |  | required |
| `threshold` | number | `1.0` |  |
| `left_amount` | string |  |  |
| `right_amount` | string |  |  |
| `amount_tolerance` | number or string | `'0'` |  |
| `left_date` | string |  |  |
| `right_date` | string |  |  |
| `date_tolerance_days` | integer | `0` |  |
| `date_format` | string |  |  |
| `mode` | `one_to_one` \| `one_to_many` | `'one_to_one'` |  |
| `left_path` | string |  | required |
| `right_path` | string |  | required |
| `limit` | integer | `1000000` |  |
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

## pdf

PDF info, text, combine, extract pages, split, protect (AES-256), watermark, form fill and optimize; confined to the run workspace.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `info` \| `text` \| `combine` \| `extract_pages` \| `split` \| `protect` \| `watermark` \| `fill_form` \| `optimize` | `'info'` |  |
| `path` | string | `'input.pdf'` |  |
| `password` | string |  | sensitive (redacted in run records) |
| `paths` | array |  |  |
| `pages` | array |  |  |
| `output_path` | string |  |  |
| `output_dir` | string | `'pages'` |  |
| `every` | integer | `0` |  |
| `before` | array |  |  |
| `open_password` | string |  | sensitive (redacted in run records) |
| `permissions_password` | string |  | sensitive (redacted in run records) |
| `printing` | `none` \| `low` \| `high` | `'high'` |  |
| `allow_copy` | boolean | `True` |  |
| `watermark_text` | string |  |  |
| `opacity` | number | `0.3` |  |
| `rotation` | number | `45` |  |
| `form_values` | object |  |  |

Fields by operation:

- `info`: `path`, `password`
- `text`: `path`, `password`, `pages`, `output_path`
- `combine`: `paths`, `output_path`
- `extract_pages`: `path`, `password`, `pages`, `output_path`
- `split`: `path`, `password`, `every`, `before`, `output_dir`
- `protect`: `path`, `password`, `open_password`, `permissions_password`, `printing`, `allow_copy`, `output_path`
- `watermark`: `path`, `password`, `watermark_text`, `opacity`, `rotation`, `pages`, `output_path`
- `fill_form`: `path`, `password`, `form_values`, `output_path`
- `optimize`: `path`, `password`, `output_path`

## playwright_robot

Run a browser robot from a declarative step list, with API-token, form or form+email-OTP login and reusable per-portal sessions.

Only an Admin can save a workflow that uses this activity.

| Input | Type | Default | Notes |
|---|---|---|---|
| `browser` | `chromium` \| `firefox` \| `webkit` | `'chromium'` |  |
| `headless` | boolean | `True` |  |
| `base_url` | string |  |  |
| `start_url` | string |  |  |
| `steps` | array |  |  |
| `operation` | `none` \| `api_token` \| `form` \| `form_otp` | `'none'` |  |
| `portal` | string |  |  |
| `login_url` | string |  |  |
| `username` | string |  |  |
| `password` | string |  | sensitive (redacted in run records) |
| `otp` | string |  | sensitive (redacted in run records) |
| `api_token` | string |  | sensitive (redacted in run records) |
| `api_token_header` | string | `'X-API-Token'` |  |
| `username_selector` | string | `'input[name=username], #username, input[type=email]'` |  |
| `password_selector` | string | `'input[name=password], #password, input[type=password]'` |  |
| `submit_selector` | string | `'button[type=submit], #login'` |  |
| `otp_selector` | string | `'input[name=otp], input[name=code], #otp, input[autocomplete=one-time-code]'` |  |
| `otp_submit_selector` | string | `'button[type=submit], #verify'` |  |
| `otp_resend_selector` | string |  |  |
| `login_failure_markers` | array |  |  |
| `login_failure_selector` | string | `'body'` |  |
| `session_check_url` | string |  |  |
| `state_file` | string |  |  |
| `otp_graph_base_url` | string | `'https://graph.microsoft.com/v1.0'` |  |
| `otp_login_base_url` | string | `'https://login.microsoftonline.com'` |  |
| `otp_tenant_id` | string |  |  |
| `otp_client_id` | string |  |  |
| `otp_client_secret` | string |  | sensitive (redacted in run records) |
| `otp_mailbox` | string |  |  |
| `otp_sender` | string |  |  |
| `otp_regex` | string | `'\\b(\\d{6})\\b'` |  |
| `otp_since` | string |  |  |
| `otp_timeout_seconds` | number | `120` |  |
| `otp_poll_seconds` | number | `2` |  |
| `otp_attempts` | integer | `2` |  |
| `screenshot_path` | string | `'page.png'` |  |
| `screenshot_on_failure` | boolean | `True` |  |
| `timeout_ms` | integer | `30000` |  |

Fields by operation:

- `none`: `start_url`, `username`, `password`
- `api_token`: `start_url`, `api_token`, `api_token_header`, `login_url`
- `form`: `login_url`, `username`, `password`, `username_selector`, `password_selector`, `submit_selector`, `login_failure_markers`, `login_failure_selector`
- `form_otp`: `login_url`, `username`, `password`, `username_selector`, `password_selector`, `submit_selector`, `otp_selector`, `otp_submit_selector`, `otp_resend_selector`, `login_failure_markers`, `login_failure_selector`, `otp_graph_base_url`, `otp_login_base_url`, `otp_tenant_id`, `otp_client_id`, `otp_client_secret`, `otp_mailbox`, `otp_sender`, `otp_regex`, `otp_since`, `otp_timeout_seconds`, `otp_poll_seconds`, `otp_attempts`

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

Run a Python script in its own process with the run workspace as its folder (process isolation, not a sandbox; Admin-only).

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

## spreadsheet

Calculate workbooks with the pure-Python formula engine: recalculate formulas, fill a model's inputs and read its results, read computed ranges, evaluate, convert, check.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `recalculate` \| `calculate` \| `read_range` \| `evaluate` \| `convert` \| `check` | `'recalculate'` |  |
| `path` | string | `'book.xlsx'` |  |
| `sheet` | string |  |  |
| `output_path` | string |  |  |
| `values` | object |  |  |
| `formulas` | object |  |  |
| `read` | array |  |  |
| `range` | string | `'used'` |  |
| `header` | boolean | `True` |  |
| `formula` | string |  |  |
| `tolerance` | number | `1e-09` |  |
| `fail_on_mismatch` | boolean | `True` |  |
| `timeout_seconds` | integer | `300` |  |

Fields by operation:

- `recalculate`: `path`, `output_path`
- `calculate`: `path`, `sheet`, `values`, `formulas`, `read`, `output_path`
- `read_range`: `path`, `sheet`, `range`, `header`, `output_path`
- `evaluate`: `path`, `sheet`, `formula`
- `convert`: `path`, `sheet`, `output_path`
- `check`: `path`, `tolerance`, `fail_on_mismatch`

## txt_log

Append or read a plain-text log with a line cap.

| Input | Type | Default | Notes |
|---|---|---|---|
| `operation` | `read` \| `append` \| `write` | `'append'` |  |
| `path` | string | `'run.log'` |  |
| `text` | string |  |  |
| `lines` | array |  |  |
| `encoding` | string | `'utf-8'` |  |
| `max_lines` | integer | `10000` |  |

Fields by operation:

- `read`: `path`, `encoding`, `max_lines`
- `append`: `path`, `encoding`, `text`, `lines`
- `write`: `path`, `encoding`, `text`, `lines`

## unc_archive

Copy or move a file to a UNC/network path and verify its SHA-256. The destination must be inside a folder listed in the server's activities.archive_roots.

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
| `max_entries` | integer | `10000` |  |

Fields by operation:

- `extract`: `path`, `output_dir`, `password`, `max_total_bytes`, `max_entries`
- `list`: `path`, `password`
- `create`: `path`, `files`, `password`
