<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
</script>

<template>
  <div class="app">
    <header class="app__bar">
      <RouterLink to="/" class="app__brand" aria-label="WorkTree home"><WorkTreeLogo /></RouterLink>
      <nav aria-label="Main">
        <RouterLink to="/design">Design language</RouterLink>
      </nav>
    </header>
    <main class="app__main"><RouterView /></main>
  </div>
</template>

<style scoped>
.app__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacingVerticalS) var(--uaf-page-padding);
  border-bottom: var(--strokeWidthThin) solid var(--uaf-border);
}
.app__brand {
  display: inline-flex;
  text-decoration: none;
}
.app__main {
  padding: var(--uaf-page-padding);
}
nav a {
  color: var(--colorBrandForegroundLink);
}
</style>
