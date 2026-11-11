<script setup lang="ts">
// The WorkTree logo: the Bloom (docs/05-logo-redesign.md). Five petals, each a different flower,
// around a Night soil centre with a light core, beside a one-colour wordmark. The petals never change
// with the theme; only the centre and the wordmark do. High contrast shows the one-colour mark.
// Lockup: the gap is a third of the mark's width and the cap height about 40 percent of its height.
withDefaults(defineProps<{ size?: number; markOnly?: boolean }>(), { size: 28 })

// Clockwise from the top: Hibiscus, Marigold, Fern, Morning glory, Orchid. Do not reorder.
const PETALS = ['var(--wt-hibiscus)', 'var(--wt-marigold)', 'var(--wt-fern)', 'var(--wt-morning-glory)', 'var(--wt-orchid)']
const PETAL = 'M0 0C9.5 -6.3 9.5 -15.75 0 -21C-9.5 -15.75 -9.5 -6.3 0 0Z'
const MONO_PETAL = 'M0 -8C6.5 -11.5 6.5 -18 0 -22C-6.5 -18 -6.5 -11.5 0 -8Z'
</script>

<template>
  <span class="logo" role="img" aria-label="WorkTree" :style="{ gap: `${Math.round(size / 3)}px` }">
    <svg class="logo__mark logo__mark--colour" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <g transform="translate(24 24)">
        <path v-for="(colour, i) in PETALS" :key="colour" :transform="`rotate(${i * 72})`" :fill="colour" :d="PETAL" />
      </g>
      <circle class="logo__centre" cx="24" cy="24" r="6.2" />
      <circle class="logo__core" cx="24" cy="24" r="2.2" />
    </svg>
    <svg class="logo__mark logo__mark--mono" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <g transform="translate(24 24)" fill="currentColor">
        <path v-for="i in 5" :key="i" :transform="`rotate(${(i - 1) * 72})`" :d="MONO_PETAL" />
        <circle r="4.2" />
      </g>
    </svg>
    <span v-if="!markOnly" class="logo__word" :style="{ fontSize: `${Math.round(size * 0.58)}px` }" aria-hidden="true">WorkTree</span>
  </span>
</template>

<style scoped>
.logo {
  display: inline-flex;
  align-items: center;
  color: var(--wt-ink);
}
.logo__centre {
  fill: var(--wt-ink);
}
.logo__core {
  fill: var(--wt-surface);
}
.logo__mark--mono {
  display: none;
}
:global(:root[data-theme='high-contrast']) .logo__mark--colour {
  display: none;
}
:global(:root[data-theme='high-contrast']) .logo__mark--mono {
  display: block;
}
.logo__word {
  font-family: var(--wt-font-head);
  font-weight: var(--weight-bold);
  line-height: 1;
  letter-spacing: var(--tracking-head);
}
</style>
