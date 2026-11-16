import type { Facets } from './api'

/** Location suggestions for pickers: countries, then states/regions, then cities. Any other
 * place can be typed in (the filter also matches the full written location). */
export function locationOptions(f: Facets | undefined) {
  if (!f) return []
  return [
    ...f.countries.map((c) => ({ value: c.value, count: c.count, hint: 'country' })),
    ...(f.regions ?? []).map((r) => ({ value: r.value, count: r.count, hint: r.country ? `state · ${r.country}` : 'state' })),
    ...f.cities.map((c) => ({ value: c.value, count: c.count, hint: c.country })),
  ]
}
