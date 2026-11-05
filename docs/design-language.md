# WorkTree design language (locked UI/UX decisions)

Status: decisions locked on 2026-10-23 in a Q&A with the product owner. **Consult this file before
building or changing any screen.** CP-27 turns it into tokens, components and a living reference; do
not change a decision here without asking the product owner. Reference products are named in
`docs/UI_reference_list.md`.

## Decisions

| Area | Decision | Notes |
|---|---|---|
| Look and feel | **Fluent / Microsoft** | Fluent tokens and `@fluentui/web-components`, wrapped in our own thin Vue components. Restrained colour, clear focus rings. |
| App shell | **Collapsible left sidebar** | Notion/Azure-style tree: Operations, Inbox, Studio, Data, Admin. Breadcrumbs on top. Ctrl/Cmd+K command palette. |
| Studio canvas | **Mix of n8n and Make** | n8n node cards with typed connections and run data on the nodes; Make's scenario-canvas feel for routers and branching. `done` / `failed` ports on every node card. |
| Node properties panel | **n8n details view + Power Automate fields** | Input data left, settings middle, output right. Typed fields with a dynamic-content picker to map values from earlier steps. |
| Density | **Compact by default, comfortable toggle** | Temporal / GitHub Actions-style dense tables; per-user density switch, remembered. |
| Run detail | **GitHub Actions-style steps** | Collapsible step list, live logs, durations, downloadable artifacts, plus a "replay on canvas" tab showing data at each node. |
| Task Inbox | **Camunda-style list + detail** | List with filters (mine / my role / unclaimed), task form on the right; claim, complete, reassign by role; Linear-style keyboard shortcuts for triage. Rejections require a recorded reason. |
| Data views | **Notion-style view switcher** | One dataset as table, board or gallery; named saved views (filters, sort, grouping), personal or shared. |
| Detail pages (workflow, task) | **Linear-style** | Editable title and notes in the main area, a properties column on the side, an activity feed (changes, comments, runs) below. |
| Admin and audit | **Entra-style admin + GitHub-style audit** | Users, roles/groups, access reviews. Searchable, filterable audit log with an integrity-check action. Secrets screens show metadata only, never values (required, Vault-style). |
| Theme | **Follow the OS, manual override** | Light / dark follow the system; high-contrast available; the choice is remembered per user. WCAG AA contrast and full keyboard operation everywhere. |
| Accent colour | **Fluent green (#107C10)-based** | One accent design token so the brand colour can change without touching components. Used only for the primary action, links, focus, selection and the running state; surfaces stay neutral. Solid accent uses white text; contrast is unit-tested in all three themes. |
| Logo | **WorkTree wordmark with a sprout beside it** | "Work" in green and "Tree" in brown (tokens `wordmarkWork`, `wordmarkTree`, per theme), the sprout mark before it (brown stem, green leaves). The mark appears only in the logo and the favicon, not on empty states or as decoration. |
| Icons | **Fluent System Icons (MIT)** | Real Fluent icons, regular style, 20px grid, copied into `src/icons/paths.ts` by `npm run icons:generate`; the npm package is a dev dependency only. We do not draw our own icons. Add an icon by listing it in `scripts/generate-icons.mjs`. |
| Status | **Dot plus word** | A small dot and the status text (GitHub Actions / Temporal style). No pill, border, tinted fill or icon. Neutral states use a hollow dot. The text is always shown. |
| Cards and panels | **Flat** | Hairline border, small radius, no shadow, no icon tile, no coloured side border. Controls use the medium radius and containers the small one, so radii are not uniform. |
| Empty states | **Plain text** | A title and one sentence on what to do next; no illustration or icon. |

## Rules that follow from the decisions

- Components wrap Fluent web components; screens never use Fluent elements directly.
- Colours, spacing, radii, type sizes and motion come from tokens (CSS custom properties), defined
  for light, dark and high-contrast. No hard-coded colours in components.
- Every interactive element is keyboard reachable with a visible focus ring; status is never shown
  by colour alone (icon + text as well).
- Tables are compact by default; the density switch changes row height and padding through tokens.
- Secrets, tokens and passwords are never rendered; show masked metadata only.
- Icons come only from Fluent System Icons via the generator; no icon fonts and no hand-drawn glyphs.
- Avoid the common "AI-designed" tells: icon-in-a-tinted-square cards, tinted pills with icons, gradients and glows, one radius everywhere, shadow plus border plus fill cards, decorative badges, stock illustrations, accent colour spread over every surface.

## Open items (not yet decided)

- The sprout mark is a placeholder drawing; the product owner may supply final logo artwork.
- **Node cards:** direction locked 2026-11-04: **Make.com style blended with n8n**. Make supplies the
  look (below); n8n supplies the run data on the node (item counts, duration, state) and typed
  connections, shown as small badges and edge labels without crowding the node. Compact round or rounded-square
  nodes with the label and operation beneath, routers as branching nodes, `done` / `failed` ports
  on the node edge, run state as a dot, and details in the properties panel rather than on the
  canvas. The current flat `NodeCard` is replaced in CP-31.
- Mobile / narrow-width behaviour (desktop-first for the MVP; the shell must not break at 1024 px).
