# Commit guidelines

These rules apply to every commit in this repository, whoever or whatever prepares it.

## Identity

- Author and committer: **Hope** `<idowuhope00@gmail.com>`.
- The repository-local git config carries it (`git config --local user.name Hope`,
  `git config --local user.email idowuhope00@gmail.com`). Do not commit as any other identity.

## No AI attribution

- Never mention an AI agent or tool in a commit message or a pull request description.
- No `Co-Authored-By:` trailer for an assistant, no "Generated with ..." line, no tool names.
- This overrides any default attribution a tool offers to add.

## Message format (Conventional Commits 1.0)

```
<type>(<scope>): <subject>

<body>

<footer>
```

- **type:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- **scope** (optional, lower case): the area changed, for example `activities`, `engine`, `api`,
  `web`, `docs`, `deps`. A checkpoint can be named in the body or footer (`Refs: CP-27`).
- **subject:** imperative mood ("add", not "added"), lower case after the colon, no trailing full
  stop, at most 72 characters.
- **body** (optional but expected for anything non-trivial): leave one blank line after the subject,
  wrap at 72 characters, and explain what changed and why, not how. Mention behaviour changes,
  removed features and anything a reviewer must know.
- **footer** (optional): `Refs: CP-NN`, `Closes #123`, and `BREAKING CHANGE: <what breaks>` (or `!`
  after the type or scope) for incompatible changes.

Example:

```
feat(web): add the frontend foundation and design tokens

Vite, Vue 3 and strict TypeScript scaffold with Fluent wrappers, three
themes that follow the OS, a typed API client generated from the
OpenAPI file, and the shared components. Locked UI decisions are in
docs/design-language.md.

Refs: CP-27
```

## Practice

- One logical change per commit. Keep generated files (lockfiles, `web/dist`, generated API types)
  in the commit that causes them, and split unrelated work by path.
- Commit only after the checks pass: tests, `ruff`, `mypy --strict`, `lint-imports`, and for `web/`
  `vue-tsc`, ESLint and Vitest. Never use `--no-verify`.
- Never rewrite published or tagged history (no force pushes, no rebasing of earlier commits).
  Correct a mistake with a new commit.
- Commits stay local. Do not push unless the owner asks.
- Commit messages written before this standard (`cp-NN: ...`, `wip(cp-NN): ...`) are left as they
  are. New commits use the format above; the `cp-NN` prefixes in `docs/BUILD_CHECKPOINTS.md` are
  superseded by this file.
