# Which model for which work

Written 2026-11-11 for the WorkTree upgrade (`03-upgrade-guide.md`). Claude choices are limited to
Haiku 5.5, Sonnet 5.5 and Opus 5.5, as the owner asked. OpenCode and xkiro were checked on this
machine the same day (OpenCode v2.1.4).

## Short answer

| Situation | Use |
|---|---|
| Planning, reviewing, anything that decides a design | **Opus 5.5, medium** |
| Engine, security, secrets, migrations, runner isolation | **Opus 5.5, high** |
| All UI and the Studio canvas | **Opus 5.5, medium** (canvas: high) |
| Ordinary backend features and tests from a clear plan | **Sonnet 5.5, medium** (high when it touches several modules) |
| Mechanical work: renames, regenerating files, fixtures, small fixes | **Haiku 5.5, low** |
| Low on Claude usage | **`opencode/deepseek-v4.1-flash-free`**, one task at a time |
| OpenCode limit reached, or a second opinion on a diff | **`xkiro/mistralai/devstral-medium`**, sparingly |

## Claude: model and effort by phase

Effort levels: low, medium, high. Higher effort costs more of the session, so use it only where
a mistake is expensive.

| Phase of the upgrade | Work | Model | Effort |
|---|---|---|---|
| Any | Orchestrating, writing briefs, reviewing diffs, deciding between options | Opus 5.5 | medium |
| 0 Truth and tooling | CI workflow, README, removing dead settings | Sonnet 5.5 | medium |
| 0 | Alembic as the only schema path | Sonnet 5.5 | high |
| 0 | `uaf` to `worktree` rename (wide, mechanical, needs care with compatibility) | Sonnet 5.5 | medium |
| 1 Security | Secret policy (ADR 0001), encrypted secret store, keyed audit chain | Opus 5.5 | high |
| 1 | Masking run fields, SMTP fix, headers, socket close, failed-login actor | Sonnet 5.5 | medium |
| 1 | Password change, idle timeout, sessions, webhook tokens | Sonnet 5.5 | high |
| 2 Database | PostgreSQL support, foreign keys and constraints, user-id normalisation | Sonnet 5.5 | high |
| 2 | Reviewing every migration before it merges | Opus 5.5 | medium |
| 2 | Folder access and the scoping helper (a missed route is a data leak) | Opus 5.5 | high |
| 2 | Retention job, file store interface, `db copy` | Sonnet 5.5 | medium |
| 3 Engine v2 | Per-run locking, tokens, engine-side nodes, cancel, idempotency | Opus 5.5 | high |
| 3 | Expression parser and evaluator | Opus 5.5 | high |
| 3 | v1 to v2 converter and its property tests | Sonnet 5.5 | high |
| 4 Workers | Runner identity, resource limits, signed packages | Opus 5.5 | high |
| 4 | Role split, heartbeats, pools, log streaming | Sonnet 5.5 | high |
| 5 API | `/api/v1`, pagination, new resources | Sonnet 5.5 | medium |
| 5 | Live event stream with permission filtering | Sonnet 5.5 | high |
| 5b Connectors | Value types, connections, the connector framework, sensitive values, locks | Opus 5.5 | high |
| 5b | Regrouping the 27 activities into apps (same code, new shape) | Sonnet 5.5 | medium |
| 5b | Individual operations once the framework exists | Sonnet 5.5 | medium |
| 5b | Match and One-time code skills | Opus 5.5 | medium |
| 6 Console | Reskin, shared components, every screen | Opus 5.5 | medium |
| 6 | Studio canvas, node panels, the widget library | Opus 5.5 | high |
| 6 | Pure TypeScript logic with no visual part (graph conversion, layout, validation) | Sonnet 5.5 | high |
| 7 Operations | Metrics, health checks, rollups, runbook | Sonnet 5.5 | medium |
| Any | Renames, path changes, regenerating reference files, test fixtures, commit messages, reading a stack trace | Haiku 5.5 | low |

**Rules of thumb**

- If the task could leak a secret, lose a run or corrupt data when done wrong, it is Opus at high.
- If the plan is already written and the task is to follow it, it is Sonnet at medium.
- If you could describe the whole task in two sentences and check it with one command, it is Haiku.
- UI is always Opus (the owner's standing rule). UI written by anything else gets an Opus pass.
- Do not use Haiku for anything that needs to hold several files in mind at once.

## OpenCode and xkiro: what is there

`opencode models` listed 61 models: 15 under `opencode/` and 46 under `xkiro/`. A listing does not
mean a model works, so 15 likely candidates were each sent a one-word request.

| Model | Result on 2026-11-11 |
|---|---|
| `opencode/deepseek-v4.1-flash-free` | Answered in 6 s |
| `opencode/glm-5.3-flash-free` | Answered in 6 s |
| `opencode/mimo-v2.6-flash-free` | Answered in 7 s |
| `opencode/minimax-m3.1-flash-free` | Answered in 5 s |
| `opencode/big-pickle` | Answered in 5 s |
| `opencode/flint-40b-free` | Answered in 5 s |
| `opencode/iceman-free` | Answered in 5 s |
| `opencode/inkling-2-small-free` | Answered in 5 s |
| `opencode/longcat-2.5-free` | Answered in 9 s |
| `opencode/nemotron-3.5-super-vl-free` | Answered in 9 s |
| `opencode/beam-free` | **Refused**: "not available in your country" |
| `xkiro/mistralai/devstral-medium` | Answered in 4 s |
| `xkiro/stealth/big-pickle` | Answered in 17 s |
| `xkiro/qwen/qwen3.8-max:free` | **Gone**: "does not exist", though still listed |
| `xkiro/qwen/qwen3-coder-plus:free` | **Gone**: "does not exist", though still listed |

Not tested: `opencode/claude-fable-5-2`, `opencode/gemini-4-carbon` and `opencode/muse-ember-1.0`
(not marked free), the other 17 Qwen entries under `xkiro/` (two of two tested were gone, so expect
the rest to be), and the remaining xkiro models (to save the limited xkiro allowance).

**What this does and does not show.** A one-word reply shows a model is reachable. It does not show
it can do real work: on 2026-11-05 a model answered a ping and then refused a real task because the
free limit had been reached. Only `opencode/deepseek-v4.1-flash-free` has actually completed a task
in this repository (one narrow brief, correct first time). The order below rests on that, not on
any benchmark.

## OpenCode: recommended order

You can run one OpenCode model at a time, and the free limit is shared across all `opencode/` free
models. So choose one, run one task, and move down the list only if a model itself fails. If a
model reports the usage limit, stop: the others will report it too.

| Order | Model | Why |
|---|---|---|
| 1 | `opencode/deepseek-v4.1-flash-free` | The only one proven on a real task here |
| 2 | `opencode/glm-5.3-flash-free` | Second in the order already agreed; answered promptly |
| 3 | `opencode/mimo-v2.6-flash-free` | Third in the agreed order; answered promptly |
| 4 | `opencode/minimax-m3.1-flash-free` | Untried on real work; answered promptly |
| 5 | `opencode/big-pickle` | Untried on real work; answered promptly |

`flint-40b-free`, `iceman-free`, `inkling-2-small-free`, `longcat-2.5-free` and
`nemotron-3.5-super-vl-free` also answer. Nothing is known about how well they code, so try one only
on a throwaway task first.

## xkiro: keep it for two jobs

xkiro's allowance is small, so do not use it for routine work.

| Job | Model |
|---|---|
| Independent review of a diff written by another model | `xkiro/mistralai/devstral-medium` |
| A simple task when OpenCode has hit its limit | `xkiro/mistralai/devstral-medium` |
| Fallback if that fails | `xkiro/stealth/big-pickle` (slower: 17 s to answer) |

The earlier reviewer, `xkiro/qwen/qwen3.8-max:free`, no longer exists.

## What "simple work" means for a free model

**Good to hand over** (the design is decided, the check is one command):

- Path and name changes across files, with the exact list given.
- A test for a function that already exists, with the cases listed.
- A fixture or a fake service extended in a stated way.
- One operation of a connector once the framework and a finished example exist.
- A CI workflow file from a written list of steps.
- Regenerating reference files and fixing what the freshness checks report.
- Documentation edits from a stated outline.

**Never hand over**

- Sign-in, sessions, secrets, the audit chain, the engine, the queue, migrations.
- Any UI, component or screen.
- Anything where the brief would have to say "decide how".
- Loosening a test or a threshold.

## How to brief a free model

1. One task per run. State the goal, the exact files it may touch, what it must not touch, and the
   command that proves it is done.
2. Paste the repository's known traps into the brief (they are listed in the delegation notes): the
   Alembic URL override, CRLF files, pytest already passing `-q`, no AI attribution in commits, no
   commit or push.
3. Before a long task, send the one-word ping with a 60-second limit:
   `opencode run -m <model> "Reply with only the word pong." < /dev/null`
4. Treat the model's report as a claim. Re-run the checks and read the diff.
5. If the same task fails review three times, take it back to Claude.

## When Claude usage is low

| Remaining work | Do this |
|---|---|
| A simple task from the list above | OpenCode, model 1 |
| A medium backend task with a clear plan | Wait for Claude if you can. If not, split it into simple tasks and give them to OpenCode one at a time, then review the whole diff on Sonnet at medium when usage returns |
| Engine, security, migrations, UI | Wait. These are not worth the risk on a free model |
| Reviewing what a free model wrote | xkiro `devstral-medium` for a first look, then Sonnet at medium before it merges |
