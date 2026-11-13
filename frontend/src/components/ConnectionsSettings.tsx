import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Link2, Lock, RefreshCw, TriangleAlert, Users } from 'lucide-react'
import { useState } from 'react'
import { api, type AppSettings } from '../lib/api'
import { Button, Input, useToast } from './ui'

function ago(iso?: string | null): string {
  if (!iso) return 'never'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

const hostOf = (url?: string | null) => (url ? url.replace(/^https?:\/\//, '') : '')

/** Settings → Team connections: join with an invite link (default), or a connection string (advanced). */
export function ConnectionsSettings({ settings }: { settings: AppSettings }) {
  const qc = useQueryClient()
  const toast = useToast()
  const c = settings.connections
  const [invite, setInvite] = useState('')
  const [advanced, setAdvanced] = useState(c.mode === 'mongo')
  const [uri, setUri] = useState('')
  const live = useQuery({
    queryKey: ['connections'],
    queryFn: api.connectionsStatus,
    enabled: c.configured,
    refetchInterval: (q) => (q.state.data?.state === 'pulling' || q.state.data?.state === 'pushing' ? 2000 : 15000),
  })
  const st = live.data ?? c
  const busy = st.state === 'pulling' || st.state === 'pushing'
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['settings'] })
    qc.invalidateQueries({ queryKey: ['connections'] })
    qc.invalidateQueries({ queryKey: ['facets'] })
  }

  const join = useMutation({
    mutationFn: (link: string) => api.joinTeam(link),
    onSuccess: (r) => {
      setInvite('')
      refresh()
      toast(`Connected${r.name ? ` as ${r.name}` : ''}. Bringing in your team's connections…`)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const leave = useMutation({
    mutationFn: api.leaveTeam,
    onSuccess: () => {
      refresh()
      toast('Disconnected from your team')
    },
  })
  const saveUri = useMutation({
    mutationFn: (value: string) => api.updateSettings({ mongodb_uri: value }),
    onSuccess: (_d, value) => {
      setUri('')
      refresh()
      toast(value ? 'Connected. Syncing in the background.' : 'Disconnected')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const sync = useMutation({
    mutationFn: () => api.syncConnections(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections'] })
      toast('Syncing with your team…')
    },
  })

  return (
    <div className="space-y-4">
      {c.configured && (
        <div className="flex items-start gap-3 rounded-md bg-sunken p-3" data-testid="connections-status">
          {st.state === 'error' ? (
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-danger" />
          ) : (
            <Users className="mt-0.5 size-5 shrink-0 text-ink" />
          )}
          <div className="min-w-0 flex-1 text-[13.5px]">
            <p className="truncate font-medium">
              {c.mode === 'team' ? `${c.team?.name ? `${c.team.name} · ` : ''}${hostOf(c.team?.server)}` : (c.host ?? 'Database')}
            </p>
            {st.state === 'error' ? (
              <p className="text-danger">{st.error}</p>
            ) : busy ? (
              <p className="inline-flex items-center gap-1.5 text-muted">
                <RefreshCw className="size-3.5 animate-spin" /> {st.state === 'pulling' ? 'Bringing in connections…' : 'Saving resumes…'}
              </p>
            ) : (
              <p className="inline-flex items-center gap-1.5 text-muted">
                <CheckCircle2 className="size-3.5 text-ok" />
                {(st.profiles ?? 0).toLocaleString()} connections · {(st.cvs_pushed ?? 0).toLocaleString()} resumes shared · synced{' '}
                {ago(st.last_pull_at)}
              </p>
            )}
          </div>
          <div className="flex shrink-0 flex-col gap-1.5 sm:flex-row">
            <Button size="sm" onClick={() => sync.mutate()} disabled={busy || sync.isPending} data-testid="connections-sync">
              <RefreshCw className="size-4" /> Sync now
            </Button>
            {c.mode === 'team' && (
              <Button size="sm" variant="ghost" onClick={() => leave.mutate()} disabled={leave.isPending}>
                Disconnect
              </Button>
            )}
          </div>
        </div>
      )}

      {c.mode !== 'team' && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (invite.trim()) join.mutate(invite.trim())
          }}
        >
          <label htmlFor="invite-link" className="text-[13px] font-medium">
            Invite link
          </label>
          <div className="flex gap-2">
            <Input
              id="invite-link"
              autoComplete="off"
              spellCheck={false}
              placeholder="Paste the invite link you received"
              value={invite}
              onChange={(e) => setInvite(e.target.value)}
              data-testid="invite-link"
            />
            <Button type="submit" variant="primary" disabled={!invite.trim() || join.isPending}>
              <Link2 className="size-4" /> {join.isPending ? 'Connecting…' : 'Connect'}
            </Button>
          </div>
          <p className="text-[12.5px] text-muted">
            Ask the person who manages your team's connections for an invite link. One click on it, or paste it here.
          </p>
        </form>
      )}

      {c.mode !== 'team' && (
        <details open={advanced} onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)} className="text-[13px]">
          <summary className="cursor-pointer text-muted hover:text-text">Advanced: connect with a database connection string</summary>
          <div className="mt-3 space-y-2">
            {c.locked ? (
              <p className="flex items-center gap-1.5 text-[12.5px] text-muted">
                <Lock className="size-3.5" /> Set in the configuration file (.env).
              </p>
            ) : (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (uri.trim()) saveUri.mutate(uri.trim())
                }}
              >
                <Input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="mongodb+srv://user:password@cluster.mongodb.net/"
                  value={uri}
                  onChange={(e) => setUri(e.target.value)}
                  data-testid="connections-uri"
                  aria-label="Connection string"
                />
                <div className="flex gap-2">
                  <Button type="submit" size="sm" disabled={!uri.trim() || saveUri.isPending}>
                    {saveUri.isPending ? 'Connecting…' : c.mode === 'mongo' ? 'Change' : 'Connect'}
                  </Button>
                  {c.mode === 'mongo' && (
                    <Button type="button" size="sm" variant="ghost" onClick={() => saveUri.mutate('')}>
                      Disconnect
                    </Button>
                  )}
                </div>
                <p className="text-[12.5px] text-muted">For administrators. Stored only on this computer; never shown again.</p>
              </form>
            )}
          </div>
        </details>
      )}
    </div>
  )
}
