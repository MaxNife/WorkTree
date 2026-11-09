# WorkTree design language (locked UI/UX decisions)

Status: decisions locked in Q&As with the product owner on 2026-10-23, 2026-11-04 and 2026-11-06.
**Consult this file before building or changing any screen.** The living reference is the `/design`
page in the app; do not change a decision here without asking the product owner. Reference products are
named in `docs/UI_reference_list.md`, and the canvas research is in `docs/research/canvas-design/`.

## The idea

WorkTree is calm and warm where people read and decide, and expressive only where they build. Three
principles, shown at the top of `/design`:

1. **Calm by default.** Warm neutrals, soft corners and dense tables. Nothing competes with the work.
2. **Colour grows from the workflows.** Vivid family colours belong to workflows: their nodes,
   avatars, cards and chart streams. The interface itself stays calm, and green marks the one main
   action.
3. **Every state in words.** A status mark always comes with its word, every control has a visible focus ring,
   and contrast passes in all themes.

The nature theme is in shapes and warmth (growth rings, petals, branches, seeds), not in green and
brown everywhere.

## Decisions

| Area | Decision | Notes |
|---|---|---|
| Look and feel | **WorkTree's own: warm, soft, nature-shaped** | Our own Vue components on native HTML elements, styled only by our tokens. No third-party UI kit. Replaced the Fluent look on 2026-11-06. |
| App shell | **Collapsible left sidebar** | Notion/Azure-style tree: Home, Operations, Inbox, Studio, Data, Connections, Insights, Admin (Home, Connections and Insights added 2026-11-09). Breadcrumbs on top. Ctrl/Cmd+K command palette. The full screen list is the sitemap in `docs/research/canvas-design/HANDOFF.md`. |
| Studio canvas | **Rings and Bloom** | Nodes are tree cross-sections in their family colour, routers open like flowers, branches thicken with item count. n8n supplies typed connections and run data on the node. `done` / `failed` ports on every node. Decided 2026-11-04 (Make look, n8n data) and 2026-11-05 (Rings and Bloom). Details below. |
| Node properties panel | **Input, settings, output** | Input data left, settings middle, output right, with a dynamic-content picker to map values from earlier steps. |
| Density | **Compact by default, comfortable toggle** | Temporal / GitHub Actions-style dense tables; per-user density switch, remembered. |
| Run detail | **GitHub Actions-style steps** | Collapsible step list, live logs, durations, downloadable artifacts, plus a "replay on canvas" tab showing data at each node. |
| Task Inbox | **Camunda-style list + detail** | List with filters (mine / my role / unclaimed), task form on the right; claim, complete, reassign by role; Linear-style keyboard shortcuts for triage. Rejections require a recorded reason. |
| Data views | **Notion-style view switcher** | One dataset as table, board or gallery; named saved views (filters, sort, grouping), personal or shared. |
| Detail pages (workflow, task) | **Linear-style** | Editable title and notes in the main area, a properties column on the side, an activity feed (changes, comments, runs) below. |
| Admin and audit | **Entra-style admin + GitHub-style audit** | Users, roles/groups, access reviews. Searchable, filterable audit log with an integrity-check action. Secrets screens show metadata only, never values (required, Vault-style). |
| Theme | **Follow the OS, manual override** | Light / dark follow the system; high-contrast available; the choice is remembered per user. WCAG AA contrast and full keyboard operation everywhere. |
| Neutrals | **Warm** | Stone and parchment greys (page `#F8F6F2`, surface white, sunken `#F2EEE8` in light; warm charcoal in dark). The page is a shade darker than the cards on it. |
| Accent colour | **WorkTree green (#107C10)** | One accent design token so the brand colour can change without touching components. Used only for the primary action, links, selection and the running state; surfaces stay neutral. Solid accent uses white text in light and dark. High contrast uses a yellow accent with black text, because white on yellow fails contrast; text on solid accent always takes the colour that passes. Contrast is unit-tested in all three themes. |
| Family colours | **Workflow identity** | Nine activity family colours (`web/src/theme/families.ts`) mark workflows wherever they appear: node cores on the canvas, ring avatars beside a workflow's name, workflow cards, family dots and chart series. They never colour buttons, tables, panels, text or status. Widened from "canvas only" on 2026-11-09. |
| Focus ring | **Neutral, not accent** | Black or white by theme, cyan in high contrast (token `color-focus`). The ring must stay 3:1 against every surface. A neutral ring also keeps focus distinct from selection, which does use the accent. Decided 2026-11-05. |
| Corners | **Soft, not uniform** | Controls 8px, containers (cards, panels, tables, dialogs) 12px, pills and dots round. |
| Elevation | **Flat on the page, soft lift when floating** | Cards and panels on the page are flat: hairline border, no shadow. What floats above the page (menus, popovers, toasts, dialogs, canvas toolbars) gets one soft warm shadow (`--uaf-shadow-float`, `--uaf-shadow-overlay`). High contrast has no shadows. |
| Type | **System font** | `Segoe UI Variable Text`, `Segoe UI`, then the platform UI font; `Cascadia Mono` / Consolas for code. No web font, because an on-premise install must not fetch one and a licensed font would need the owner's approval. |
| Logo | **WorkTree wordmark with a sprout beside it** | "Work" in green and "Tree" in brown (tokens `wordmark-work`, `wordmark-tree`, per theme), the sprout mark before it (brown stem, green leaves). The mark appears only in the logo and the favicon, not on empty states or as decoration. |
| Icons | **Phosphor Icons (MIT)** | Chosen by the owner on 2026-11-06 over Solar and Hugeicons: soft and rounded, with leaf, plant and tree icons. Regular weight in the interface; fill weight on coloured shapes (canvas nodes) and in tight spaces. Paths are copied into `src/icons/paths.ts` by `npm run icons:generate`; `@phosphor-icons/core` is a dev dependency only. We do not draw our own icons. Add an icon by listing it in `scripts/generate-icons.mjs`. |
| Status | **Mark plus word** | A small mark and the status text. Each kind has its own shape as well as its colour: a tick for done, a cross for failed, a clock for waiting, an alert for attention, a turning ring for running, a dashed ring for neutral. No pill, border or tinted fill. The text is always shown. Changed from a plain dot on 2026-11-09 at the owner's request. |
| Empty states | **Plain text** | A title and one sentence on what to do next; no illustration or icon. |

## Rules that follow from the decisions

- Screens use our `U*` components and shared components only; they never style a native control
  themselves. The controls are native elements (`<button>`, `<input>`, `<select>`, `<textarea>`,
  `<dialog>`), so the browser gives them keyboard use and screen-reader support.
- Colours, spacing, radii, type sizes, shadows and motion come from tokens (CSS custom properties),
  defined for light, dark and high contrast in `web/src/theme/tokens.ts` and mapped to `--uaf-*` in
  `web/src/styles/base.css`. No hard-coded colours in components, except the family colours, which
  live in one file.
- Every interactive element is keyboard reachable with a visible focus ring; status is never shown
  by colour alone (the status word is always shown beside the mark, and each mark has its own shape).
- The edge of a text field, checkbox or switch keeps 3:1 against its surface (`--uaf-border-control`).
- Tables are compact by default; the density switch changes row height and padding through tokens.
- Secrets, tokens and passwords are never rendered; show masked metadata only.
- Icons come only from Phosphor via the generator; no icon fonts and no hand-drawn glyphs.
- Avoid the common "AI-designed" tells: icon-in-a-tinted-square cards, tinted pills with icons,
  gradients and glows, one radius everywhere, shadow plus border plus fill cards, decorative badges,
  stock illustrations, accent colour spread over every surface. Workflow identity is the one
  deliberate exception: a coloured core or ring is how a workflow and its family are recognised.

## Shared components (look)

- **Tables** sit in a rounded frame with a sunken header row; the selected row takes the accent tint.
- **Filter bar** is one sunken, rounded strip; search has a magnifier inside the field.
- **Tabs** show counts as small round chips; the selected tab's chip takes the accent tint.
- **Run timeline** is a vine: one stem down the left with a bud per step in its state colour.
- **Board** columns are sunken; items are white cards; an empty column says so in a dashed box.
- **Code blocks** have a header strip with the label and copy button, so nothing covers the text.
- **Loading** is a turning ring beside the word; **empty states** stay plain text in a dashed frame.

## Token names after the Fluent removal

Code written against the old Fluent names must switch to these (DECISIONS 13.2). Horizontal and
vertical spacing share one scale.

| Old (Fluent) | New |
|---|---|
| `--spacingHorizontalXXS` / `--spacingVerticalXXS` | `--space-2` |
| `XS`, `SNudge`, `S`, `MNudge`, `M` | `--space-4`, `--space-6`, `--space-8`, `--space-10`, `--space-12` |
| `L`, `XL`, `XXL`, `XXXL` | `--space-16`, `--space-20`, `--space-24`, `--space-32` |
| `--fontSizeBase100` to `--fontSizeBase600` | `--font-size-10`, `-12`, `-14`, `-16`, `-20`, `-24` |
| `--lineHeightBase100` to `--lineHeightBase600` | `--line-height-14`, `-16`, `-20`, `-22`, `-28`, `-32` |
| `--fontWeightRegular` / `Medium` / `Semibold` / `Bold` | `--weight-regular` / `-medium` / `-semibold` / `-bold` |
| `--strokeWidthThin` / `Thick` / `Thicker` / `Thickest` | `--stroke-1` / `-2` / `-3` / `-4` |
| `--durationFaster`, `--durationNormal`, `--durationUltraSlow` | `--duration-fast`, `--duration-normal`, `--duration-slow` |
| `--curveEasyEase` | `--ease-standard` |
| `--fontFamilyBase` / `--fontFamilyMonospace` | `--font-family-base` / `--font-family-mono` (or `--uaf-font` / `--uaf-font-mono`) |
| `--wordmarkWork` / `--wordmarkTree` | `--wordmark-work` / `--wordmark-tree` |
| `--colorBackgroundOverlay` | `--uaf-overlay` |
| any other `--color*` | the `--uaf-*` variable for its meaning (`--uaf-surface`, `--uaf-text-muted`, `--uaf-accent` and so on) |

In tests, select our elements instead of Fluent ones: `button.u-button` (or `button`) for
`fluent-button`, `input.u-control` for `fluent-text-input`, `textarea` for `fluent-textarea`,
`select` for `fluent-dropdown`, `input[type="checkbox"]` (with `role="switch"` for a switch) for
`fluent-checkbox` and `fluent-switch`, and `dialog` with `.u-dialog__footer` for `fluent-dialog` and its
`action` slot. jsdom lacks `showModal()`, so `web/tests/setup.ts` adds it.

## Canvas: Rings and Bloom

The Studio canvas is where WorkTree is expressive. Research, options and the full board of node kinds,
setup templates and builder screens are in `docs/research/canvas-design/HANDOFF.md`.

- **Activity node:** a tree cross-section. Slightly uneven rings in the family colour around a solid
  core with a white (or, for light colours, dark) fill-weight icon. The label and activity sit beneath.
- **Run state:** the outer ring fills as an arc (blue while running, part-way and amber while
  waiting, full green when done, dashed red when failed), plus the usual dot and word.
- **Ports:** `done` and `failed` as two small dots on the right edge of every node.
- **Branches:** connections taper and thicken with the number of items that passed, and blend between
  the colours of the nodes they join. A failed path is a sparse red dotted line.
- **Router:** a flower with one petal per route, coloured like the route's next node. It stays a bud
  until data reaches it, then opens; after a run the busier route has the larger petal (not to scale,
  with a minimum size, and labels give exact counts).
- **Other node kinds:** trigger (rings with a root cap, no input), filter (a leaf on the branch),
  merge (petals turned inward), loop (a fern curl over a grove of steps), wait (a dormant, outlined
  seed), human task (bark ring), sub-workflow (stacked rings), agent (heavy ring with roots to its
  parts), stop with failure (a cut stump).
- **Ground:** faint growth-ring contours or a soft dot grid on the page colour; floating toolbars with
  the soft shadow; add-step is a small bud.

`web/src/components/NodeCard.vue` is the activity node. The other kinds and the Vue Flow wiring are
CP-31.

## Open items (not yet decided)

- The sprout mark is a placeholder drawing; the product owner may supply final logo artwork.
- Mobile / narrow-width behaviour (desktop-first for the MVP; the shell must not break at 1024 px).
- Whether routers become their own engine node type (`docs/SYSTEM_DESIGN.md` open question 23); the
  flower router assumes yes.
- Family colours in high contrast: nodes and avatars keep their colours today; high contrast needs
  its own pass in CP-31.
- Workers and work queues: the screen is approved (2026-11-09), but workers need a spec and work
  queues need engine work before it can be built.
