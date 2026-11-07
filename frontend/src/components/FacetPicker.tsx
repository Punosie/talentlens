import * as Popover from '@radix-ui/react-popover'
import { Check, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { cn } from '../lib/utils'
import { Chip } from './ui'

type Option = { value: string; count?: number; hint?: string | null }

/** Multi-select with type-to-filter. Can also accept free text when `allowCustom` is set. */
export function FacetPicker({
  label,
  options,
  selected,
  onChange,
  placeholder = 'Type to filter…',
  allowCustom = false,
  testId,
}: {
  label: string
  options: Option[]
  selected: string[]
  onChange: (v: string[]) => void
  placeholder?: string
  allowCustom?: boolean
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const sel = useMemo(() => new Set(selected.map((s) => s.toLowerCase())), [selected])
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const list = needle ? options.filter((o) => o.value.toLowerCase().includes(needle)) : options
    return list.slice(0, 80)
  }, [q, options])

  const toggle = (v: string) => {
    if (sel.has(v.toLowerCase())) onChange(selected.filter((s) => s.toLowerCase() !== v.toLowerCase()))
    else onChange([...selected, v])
  }
  const exact = options.some((o) => o.value.toLowerCase() === q.trim().toLowerCase())

  return (
    <div data-testid={testId}>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            type="button"
            className="flex h-9 w-full items-center justify-between rounded-md border border-line-strong bg-surface px-3 text-left text-sm text-muted hover:border-ink"
            aria-label={`Choose ${label}`}
          >
            <span>{selected.length ? `${selected.length} selected` : `Any ${label.toLowerCase()}`}</span>
            <Plus className="size-4" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={6}
            className="z-50 w-[280px] rounded-md border border-line-strong bg-surface p-2 shadow-lg"
          >
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && q.trim()) {
                  e.preventDefault()
                  const first = filtered[0]?.value
                  if (allowCustom && !exact) toggle(q.trim())
                  else if (first) toggle(first)
                  setQ('')
                }
              }}
              placeholder={placeholder}
              aria-label={`Filter ${label}`}
              className="mb-2 h-9 w-full rounded border border-line-strong bg-paper px-2 text-sm focus:border-ink focus:outline-none"
            />
            <ul className="max-h-72 overflow-y-auto" role="listbox" aria-label={label}>
              {allowCustom && q.trim() && !exact && (
                <li>
                  <button
                    type="button"
                    onClick={() => {
                      toggle(q.trim())
                      setQ('')
                    }}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-sunken"
                  >
                    <Plus className="size-4" /> Add “{q.trim()}”
                  </button>
                </li>
              )}
              {filtered.map((o) => {
                const on = sel.has(o.value.toLowerCase())
                return (
                  <li key={o.value} role="option" aria-selected={on}>
                    <button
                      type="button"
                      onClick={() => toggle(o.value)}
                      className={cn(
                        'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-sunken',
                        on && 'font-semibold',
                      )}
                    >
                      <Check className={cn('size-4 shrink-0', on ? 'text-ink' : 'invisible')} />
                      <span className="min-w-0 flex-1 truncate">{o.value}</span>
                      {o.hint && <span className="truncate text-[12px] text-muted">{o.hint}</span>}
                      {o.count !== undefined && <span className="text-[12px] text-muted tabular-nums">{o.count}</span>}
                    </button>
                  </li>
                )
              })}
              {!filtered.length && !(allowCustom && q.trim()) && (
                <li className="px-2 py-3 text-sm text-muted">No matches</li>
              )}
            </ul>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {selected.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {selected.map((s) => (
            <Chip key={s} tone="ink" onRemove={() => toggle(s)}>
              {s}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}
