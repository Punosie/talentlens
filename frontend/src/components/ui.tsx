import * as Dialog from '@radix-ui/react-dialog'
import * as Tooltip from '@radix-ui/react-tooltip'
import { CircleHelp, LoaderCircle, X } from 'lucide-react'
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from '../lib/utils'

// --- buttons & inputs -----------------------------------------------------------
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-solid'
  size?: 'sm' | 'md' | 'lg'
  busy?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', busy, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--radius-control)] font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:scale-[0.98] disabled:active:scale-100',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' && 'h-8 px-3 text-[13px]',
        size === 'md' && 'h-10 px-4 text-sm',
        size === 'lg' && 'h-12 px-5 text-[15px]',
        variant === 'primary' && 'bg-ink text-on-ink shadow-e1 hover:bg-ink-strong',
        variant === 'secondary' && 'border border-line-strong bg-surface text-text shadow-e1 hover:bg-sunken',
        variant === 'ghost' && 'text-muted hover:bg-sunken hover:text-text',
        variant === 'danger' && 'border border-line-strong bg-surface text-danger hover:bg-danger-soft',
        variant === 'danger-solid' && 'bg-danger text-white hover:opacity-90',
        className,
      )}
      {...rest}
    >
      {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'h-10 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface px-3 text-sm text-text',
        'transition-colors placeholder:text-muted focus:border-ink focus:outline-none',
        className,
      )}
      {...rest}
    />
  )
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          'w-full rounded-[var(--radius-control)] border border-line-strong bg-surface p-3 text-sm leading-relaxed text-text',
          'placeholder:text-muted focus:border-ink focus:outline-none',
          className,
        )}
        {...rest}
      />
    )
  },
)

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: ReactNode }) {
  return (
    <div className="mb-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-semibold text-text">
        {children}
      </label>
      {hint && <p className="mt-0.5 text-[12px] leading-snug text-muted">{hint}</p>}
    </div>
  )
}

// --- display ------------------------------------------------------------------
export function Chip({
  children,
  tone = 'plain',
  onRemove,
  title,
}: {
  children: ReactNode
  tone?: 'plain' | 'mark' | 'missing' | 'ink' | 'ok' | 'outline'
  onRemove?: () => void
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-[12.5px] leading-5',
        tone === 'plain' && 'bg-sunken text-text',
        tone === 'mark' && 'bg-mark text-[#12181a]',
        tone === 'missing' && 'text-muted line-through decoration-line-strong',
        tone === 'ink' && 'bg-ink-soft text-ink-strong',
        tone === 'ok' && 'bg-ok-soft text-ok',
        tone === 'outline' && 'border border-line-strong text-muted',
      )}
    >
      <span className="truncate">{children}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${typeof children === 'string' ? children : 'item'}`}
          className="-mr-0.5 rounded text-muted hover:text-text"
        >
          <X className="size-3.5" />
        </button>
      )}
    </span>
  )
}

export function Card({ children, className, as: As = 'div' }: { children: ReactNode; className?: string; as?: 'div' | 'section' | 'li' }) {
  return (
    <As className={cn('rounded-[var(--radius-panel)] border border-line bg-surface shadow-e1', className)}>{children}</As>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight md:text-[28px]">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[15px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  const initials = name
    .split(/[\s_.-]+/)
    .filter((w) => /^[A-Za-zÀ-ÿ]/.test(w))
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')
  // stable, calm hue per person
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360
  return (
    <span
      aria-hidden
      className="tl-avatar inline-flex shrink-0 items-center justify-center rounded-full font-semibold"
      style={{ width: size, height: size, fontSize: size * 0.38, ['--av-h' as string]: h }}
    >
      {initials || '?'}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn('tl-skeleton block', className)} />
}

export function Progress({ value, className, label }: { value: number; className?: string; label?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)))
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-sunken', className)}
    >
      <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn('size-4 animate-spin text-muted', className)} aria-label="Loading" />
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line-strong bg-sunken px-1.5 py-0.5 font-sans text-[11px] text-muted">{children}</kbd>
  )
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-dashed border-line-strong px-6 py-12 text-center">
      {icon && <div className="flex size-12 items-center justify-center rounded-full bg-sunken text-muted">{icon}</div>}
      <p className="text-base font-semibold">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

// --- tooltips ---------------------------------------------------------------------
export function Hint({ children, content, side = 'top' }: { children: ReactNode; content: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <Tooltip.Root delayDuration={250}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side={side}
          sideOffset={6}
          className="z-[70] max-w-xs rounded-md bg-[#1d2528] px-3 py-2 text-[12.5px] leading-snug text-white shadow-e2"
        >
          {content}
          <Tooltip.Arrow className="fill-[#1d2528]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

export function HelpDot({ children, label = 'What does this mean?' }: { children: ReactNode; label?: string }) {
  return (
    <Hint content={children}>
      <button type="button" aria-label={label} className="inline-flex align-middle text-muted hover:text-text">
        <CircleHelp className="size-3.5" />
      </button>
    </Hint>
  )
}

// --- dialogs ---------------------------------------------------------------------
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  wide,
  dismissable = true,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  wide?: boolean
  dismissable?: boolean
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => (dismissable || o ? onOpenChange(o) : undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="tl-overlay fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] dark:bg-black/60" />
        <Dialog.Content
          onEscapeKeyDown={(e) => !dismissable && e.preventDefault()}
          onPointerDownOutside={(e) => !dismissable && e.preventDefault()}
          className={cn(
            'tl-modal fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100%-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto',
            'rounded-[14px] border border-line bg-surface p-6 shadow-e2 outline-none md:p-8',
            wide ? 'max-w-2xl' : 'max-w-md',
          )}
        >
          <Dialog.Title className="text-xl font-bold tracking-tight">{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className="mt-1.5 text-[14px] text-muted">{description}</Dialog.Description>
          ) : (
            <Dialog.Description className="sr-only">{title}</Dialog.Description>
          )}
          {children && <div className="mt-5">{children}</div>}
          {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
          {dismissable && (
            <Dialog.Close
              className="absolute top-4 right-4 flex size-8 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-text"
              aria-label="Close"
            >
              <X className="size-4" />
            </Dialog.Close>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  busy,
  danger,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description: ReactNode
  confirmLabel: string
  onConfirm: () => void
  busy?: boolean
  danger?: boolean
}) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={danger ? 'danger-solid' : 'primary'} onClick={onConfirm} busy={busy} data-testid="confirm">
            {confirmLabel}
          </Button>
        </>
      }
    />
  )
}

// --- toasts ----------------------------------------------------------------------
type Toast = { id: number; text: string; tone: 'info' | 'error' | 'ok'; action?: { label: string; run: () => void } }
type PushToast = (text: string, tone?: Toast['tone'], action?: Toast['action']) => void
const ToastCtx = createContext<PushToast>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback<PushToast>((text, tone = 'info', action) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t.slice(-3), { id, text, tone, action }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 8000 : 4500)
  }, [])
  const value = useMemo(() => push, [push])
  return (
    <ToastCtx.Provider value={value}>
      <Tooltip.Provider>{children}</Tooltip.Provider>
      <div className="pointer-events-none fixed top-4 left-1/2 z-[80] flex w-[calc(100%-32px)] max-w-md -translate-x-1/2 flex-col items-center gap-2 sm:top-auto sm:bottom-4 sm:left-4 sm:w-auto sm:translate-x-0 sm:items-start" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={cn(
              'tl-enter pointer-events-auto flex max-w-md items-center gap-3 rounded-lg px-4 py-3 text-sm shadow-e2',
              t.tone === 'error' ? 'bg-danger text-white' : 'bg-[#1d2528] text-white',
            )}
          >
            <span>{t.text}</span>
            {t.action && (
              <button
                type="button"
                onClick={() => {
                  t.action!.run()
                  setToasts((all) => all.filter((x) => x.id !== t.id))
                }}
                className="font-semibold text-mark underline-offset-2 hover:underline"
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)
