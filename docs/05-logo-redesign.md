# WorkTree logo: the Bloom

Written 2026-11-11. The owner chose option A (the Bloom) from three drawn options on the redesign
review sheet. The files are in `logo/`; `logo/preview.png` shows every variant on the light page
colour and on Night soil.

## Why the old one goes

The sprout was a thin green and brown line drawing. It could belong to any gardening or wellness
product, it faded at small sizes, and it showed none of the colour that the product is built
around. The design language itself called it a placeholder.

## The idea

A flower with five petals, each a different colour, around one dark centre.

- **Each petal is a step.** Different tools, different colours, working as one thing.
- **The centre is the run** that holds them together, with a small light core.
- **Five colours of equal strength** say what the product looks like before a word is read:
  vibrant, plant-shaped, many parts in one whole.
- The petals are the same shape as the router's petals on the Studio canvas, so the logo and the
  product are drawn with one hand.

## Files

| File | Use |
|---|---|
| `logo/worktree-mark.svg` | The mark on light surfaces |
| `logo/worktree-mark-dark.svg` | The mark on dark surfaces (the centre turns white) |
| `logo/worktree-mark-mono.svg` | One colour (`currentColor`): high contrast theme, print, embossing, stamps |
| `logo/worktree-lockup.svg`, `logo/worktree-lockup-dark.svg` | Mark and wordmark together |
| `logo/favicon.svg` | Browser tab |
| `logo/worktree-app-icon.svg` | Installer, desktop shortcut, sign-in page |
| `logo/preview.png` | All of the above, rendered |

## Construction

On a 48 by 48 grid, centred at (24, 24):

| Part | Geometry |
|---|---|
| Petal | An almond 21 long and 19 wide at its widest, from the centre outwards: `M0 0C9.5 -6.3 9.5 -15.75 0 -21C-9.5 -15.75 -9.5 -6.3 0 0Z` |
| Five petals | The same petal turned 0, 72, 144, 216 and 288 degrees. The first points straight up |
| Order, clockwise from the top | Hibiscus, Marigold, Fern, Morning glory, Orchid |
| Centre | Circle radius 6.2 in Night soil, with a core of radius 2.2 in white |

Later petals overlap earlier ones slightly near the centre; the centre circle covers the join.

**One-colour version.** The petals are narrower and start 8 units out from the centre, so they
stand apart from each other and from a solid centre dot. This keeps five petals readable when
colour is not available.

## Colour

| Part | Value | Name |
|---|---|---|
| Top petal | `#EE3F3A` | Hibiscus |
| Upper right | `#FFB01F` | Marigold |
| Lower right | `#0E9F5B` | Fern |
| Lower left | `#2A7BEA` | Morning glory |
| Upper left | `#E0288F` | Orchid |
| Centre | `#231F2E` on light, `#FFFFFF` on dark | Night soil |

The petals do not change between light and dark. Only the centre and the wordmark swap.

## Wordmark

"WorkTree" as one word in the device's own interface font, weight 700, slightly tight, in Night
soil (white on dark). No web font is loaded, as the owner asked.

```
font-family: 'Segoe UI Variable Display', 'Segoe UI', -apple-system, BlinkMacSystemFont,
             'SF Pro Display', Roboto, 'Helvetica Neue', Arial, sans-serif;
font-weight: 700;  letter-spacing: -0.02em;
```

The wordmark is a single colour so the Bloom carries all the colour and the name reads as one word.

## Using it

- **Clear space.** One centre-circle diameter (about a quarter of the mark's width) on every side.
- **Lockup.** The gap between mark and wordmark is one third of the mark's width. The wordmark's
  cap height is about 40 percent of the mark's height.
- **Minimum sizes.** Colour mark 16 px. One-colour mark 20 px. Lockup 20 px high.
- **Where it appears.** Top of the sidebar (lockup; mark only when collapsed), the sign-in page,
  the browser tab, the first-load screen, and the footers of generated emails and reports.

**Do not**

- Change the order or the colours of the petals, or use fewer than five.
- Put the colour mark on a coloured band or a photo. Use it on white, the page colour or Night
  soil; anywhere else use the one-colour version.
- Add a shadow, gradient, outline or glow.
- Stretch, tilt or rotate it.

**The one animation.** On the sign-in page and the first-load screen the petals may open once: each
scales from the centre in turn, 60 ms apart, 420 ms in all. It never loops. With reduced motion it
appears complete.

## Putting it in the app

None of this is done yet.

1. Replace the drawing in `web/src/components/WorkTreeLogo.vue`:

```vue
<svg class="logo__mark" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
  <g transform="translate(24 24)">
    <path v-for="(colour, i) in PETALS" :key="colour" :transform="`rotate(${i * 72})`" :fill="colour"
          d="M0 0C9.5 -6.3 9.5 -15.75 0 -21C-9.5 -15.75 -9.5 -6.3 0 0Z" />
  </g>
  <circle class="logo__centre" cx="24" cy="24" r="6.2" />
  <circle class="logo__core" cx="24" cy="24" r="2.2" />
</svg>
```

```ts
const PETALS = ['var(--wt-hibiscus)', 'var(--wt-marigold)', 'var(--wt-fern)', 'var(--wt-morning-glory)', 'var(--wt-orchid)']
```

```css
.logo__centre { fill: var(--wt-ink); }
.logo__core   { fill: var(--wt-surface); }
.logo__word   { color: var(--wt-ink); font-weight: 700; letter-spacing: -0.02em; }
```

   In the high contrast theme, render `worktree-mark-mono.svg` instead.
2. Copy `logo/favicon.svg` to `web/public/favicon.svg`.
3. Remove the `wordmark-work` and `wordmark-tree` tokens and update the logo tests.

## Checks

- Rendered in Chromium at 160, 48, 24 and 16 px on `#FBFAFE` and on `#231F2E`, plus the app icon,
  both lockups and the one-colour mark at 72 and 20 px. See `logo/preview.png`.
- A first one-colour draft used a mask and rendered wrongly; it was redrawn with separated petals
  and re-checked.

Not done: a trademark search and a print test. Do both before the mark is used outside the product.
