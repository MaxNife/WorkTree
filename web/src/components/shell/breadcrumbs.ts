// Breadcrumbs come from `meta.breadcrumb` on the matched route records (parents first). A page can
// replace the last label once it has loaded something better than a route param (a workflow name).
import { computed, onBeforeUnmount, ref, toValue, watchEffect, type ComputedRef, type MaybeRefOrGetter } from 'vue'
import { useRoute, type RouteLocationNormalizedLoaded } from 'vue-router'

export interface Crumb {
  label: string
  /** Absent on the current page. */
  to?: string
}

const lastLabel = ref<string | undefined>()

/** Build the trail for a route. */
export function breadcrumbsFor(route: RouteLocationNormalizedLoaded, last?: string): Crumb[] {
  const records = route.matched.filter((record) => record.meta.breadcrumb !== undefined)
  // Duplicate records (a parent and its '' child sharing a label) collapse to one crumb.
  const crumbs: Crumb[] = []
  for (const record of records) {
    const meta = record.meta.breadcrumb
    const label = typeof meta === 'function' ? meta(route) : (meta ?? '')
    const to = record.path.replace(/:(\w+)\??/g, (_, key: string) => {
      const value = route.params[key]
      return encodeURIComponent(Array.isArray(value) ? value.join('/') : (value ?? ''))
    })
    if (crumbs.at(-1)?.to === to) continue
    crumbs.push({ label, to })
  }
  const current = crumbs.at(-1)
  if (current) {
    delete current.to
    if (last) current.label = last
  }
  return crumbs
}

export function useBreadcrumbs(): ComputedRef<Crumb[]> {
  const route = useRoute()
  return computed(() => breadcrumbsFor(route, lastLabel.value))
}

/** Use `label` for the current page's breadcrumb while the calling component is mounted. */
export function useCrumbLabel(label: MaybeRefOrGetter<string | undefined>): void {
  const stop = watchEffect(() => {
    lastLabel.value = toValue(label) || undefined
  })
  onBeforeUnmount(() => {
    stop()
    lastLabel.value = undefined
  })
}
