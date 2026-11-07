import { LoaderCircle, X } from 'lucide-react'
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

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  busy?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', busy, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-[13px]' : 'h-10 px-4 text-sm',
        variant === 'primary' && 'bg-ink text-on-ink hover:bg-ink-strong',
        variant === 'secondary' && 'border border-line-strong bg-surface text-text hover:bg-sunken',
        variant === 'ghost' && 'text-muted hover:bg-sunken hover:text-text',
        variant === 'danger' && 'border border-line-strong bg-surface text-danger hover:bg-sunken',
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
        'h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-text',
        'placeholder:text-muted focus:border-ink focus:outline-none',
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
          'w-full rounded-md border border-line-strong bg-surface p-3 text-sm leading-relaxed text-text',
          'placeholder:text-muted focus:border-ink focus:outline-none',
          className,
        )}
        {...rest}
      />
    )
  },
)

export function Chip({
  children,
  tone = 'plain',
  onRemove,
  title,
}: {
  children: ReactNode
  tone?: 'plain' | 'mark' | 'missing' | 'ink'
  onRemove?: () => void
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded px-1.5 py-0.5 text-[12.5px] leading-5',
        tone === 'plain' && 'bg-sunken text-text',
        tone === 'mark' && 'bg-mark text-[#12181a]',
        tone === 'missing' && 'text-muted line-through decoration-line-strong',
        tone === 'ink' && 'bg-ink-soft text-ink-strong',
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

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn('size-4 animate-spin text-muted', className)} aria-label="Loading" />
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 border-l-2 border-line-strong py-6 pl-5">
      {icon && <div className="text-muted">{icon}</div>}
      <p className="text-base font-semibold">{title}</p>
      {children && <div className="max-w-prose text-sm text-muted">{children}</div>}
    </div>
  )
}

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] font-semibold text-text">
      {children}
    </label>
  )
}

// --- toasts ----------------------------------------------------------------
type Toast = { id: number; text: string; tone: 'info' | 'error' | 'ok' }
const ToastCtx = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t.slice(-3), { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 7000 : 4000)
  }, [])
  const value = useMemo(() => push, [push])
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={cn(
              'pointer-events-auto max-w-sm rounded-md border bg-surface px-4 py-3 text-sm shadow-lg',
              t.tone === 'error' ? 'border-danger text-danger' : 'border-line-strong text-text',
            )}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)
