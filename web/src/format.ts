// Locale-aware display formatting shared by the screens.
const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
const countFormat = new Intl.NumberFormat()

/** Local date and time, or `-` when the value is absent or not a date. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : dateTimeFormat.format(date)
}

/** A whole count with thousands separators. */
export function formatCount(value: number): string {
  return countFormat.format(value)
}
