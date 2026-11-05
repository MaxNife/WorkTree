<script setup lang="ts">
// The WorkTree logo: a sprout beside the wordmark, "Work" in green and "Tree" in brown.
// The mark lives only here (not on empty states or decoration). Colours come from theme tokens.
// The wordmark scales with the mark: 16px type beside the default 20px sprout.
withDefaults(defineProps<{ size?: number; markOnly?: boolean }>(), { size: 20 })
</script>

<template>
  <span class="logo" role="img" aria-label="WorkTree">
    <svg class="logo__mark" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g class="logo__trunk" fill="none" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 21V10" />
        <path d="M8.5 21h7" />
      </g>
      <g class="logo__leaf" fill="none" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 14c-4.2 0-6.5-2.4-6.5-6 4.2 0 6.5 2.4 6.5 6Z" />
        <path d="M12 11c0-3.6 2.3-6 6.5-6 0 3.6-2.3 6-6.5 6Z" />
      </g>
    </svg>
    <span v-if="!markOnly" class="logo__word" :style="{ fontSize: `${Math.round(size * 0.8)}px` }" aria-hidden="true">
      <span class="logo__work">Work</span><span class="logo__tree">Tree</span>
    </span>
  </span>
</template>

<style scoped>
.logo {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalXS);
}
.logo__trunk {
  stroke: var(--wordmarkTree);
}
.logo__leaf {
  stroke: var(--wordmarkWork);
}
.logo__word {
  font-weight: var(--fontWeightSemibold);
  line-height: 1;
  letter-spacing: -0.01em;
}
.logo__work {
  color: var(--wordmarkWork);
}
.logo__tree {
  color: var(--wordmarkTree);
}
</style>
