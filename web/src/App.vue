<script setup lang="ts">
// The router picks the layout: the app shell for signed-in pages, the bare login page otherwise.
import ToastRegion from '@/components/shell/ToastRegion.vue'
</script>

<template>
  <RouterView />
  <ToastRegion />
</template>

<style>
#app {
  height: 100%;
}
</style>
