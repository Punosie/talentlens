import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Database, Lock, RefreshCw, TriangleAlert } from 'lucide-react'
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

/** Settings → Connections database (MongoDB): connect, status, sync now. */
export function ConnectionsSettings({ settings }: { settings: AppSettings }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [uri, setUri] = useState('')
  const [editing, setEditing] = useState(false)
  const c = settings.connections
  const live = useQuery({
    queryKey: ['connections'],
    queryFn: api.connectionsStatus,
    enabled: c.configured,
    refetchInterval: (q) => (q.state.data?.state === 'pulling' || q.state.data?.state === 'pushing' ? 2000 : 15000),
  })
  const st = live.data ?? c

  const save = useMutation({
    mutationFn: (value: string) => api.updateSettings({ mongodb_uri: value }),
    onSuccess: (_d, value) => {
      setUri('')
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['connections'] })
      qc.invalidateQueries({ queryKey: ['facets'] })
      toast(value ? 'Connected. Syncing your connections in the background.' : 'Disconnected')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const sync = useMutation({
    mutationFn: () => api.syncConnections(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections'] })
      toast('Syncing with your connections database…')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const busy = st.state === 'pulling' || st.state === 'pushing'

  return (
    <div className="space-y-4">
      {c.configured && (
        <div className="flex items-start gap-3 rounded-md bg-sunken p-3" data-testid="connections-status">
          {st.state === 'error' ? (
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-danger" />
          ) : (
            <Database className="mt-0.5 size-5 shrink-0 text-ink" />
          )}
          <div className="min-w-0 flex-1 text-[13.5px]">
            <p className="truncate font-medium">{c.host ?? 'MongoDB'}</p>
            {st.state === 'error' ? (
              <p className="text-danger">{st.error}</p>
            ) : (
              <p className="text-muted">
                {busy ? (
                  <span className="inline-flex items-center gap-1.5">
                    <RefreshCw className="size-3.5 animate-spin" /> {st.state === 'pulling' ? 'Bringing in connections…' : 'Saving resumes…'}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    <CheckCircle2 className="size-3.5 text-ok" />
                    {(st.profiles ?? 0).toLocaleString()} LinkedIn connections · {(st.cvs_pushed ?? 0).toLocaleString()} resumes saved to the
                    database · synced {ago(st.last_pull_at)}
                  </span>
                )}
              </p>
            )}
          </div>
          <Button size="sm" onClick={() => sync.mutate()} disabled={busy || sync.isPending} data-testid="connections-sync">
            <RefreshCw className="size-4" /> Sync now
          </Button>
        </div>
      )}

      {c.locked ? (
        <p className="flex items-center gap-1.5 text-[12.5px] text-muted">
          <Lock className="size-3.5" /> Set in the configuration file (.env).
        </p>
      ) : !c.configured || editing ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (uri.trim()) save.mutate(uri.trim())
          }}
        >
          <label htmlFor="mongo-uri" className="text-[13px] font-medium">
            Connection string
          </label>
          <Input
            id="mongo-uri"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="mongodb+srv://user:password@cluster.mongodb.net/"
            value={uri}
            onChange={(e) => setUri(e.target.value)}
            data-testid="connections-uri"
          />
          <p className="text-[12.5px] text-muted">
            Stored only on this computer, in TalentLens's settings. It's never shown again or sent anywhere except your database.
          </p>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={!uri.trim() || save.isPending}>
              {save.isPending ? 'Connecting…' : 'Connect'}
            </Button>
            {editing && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            )}
          </div>
        </form>
      ) : (
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Change connection
          </Button>
          <Button size="sm" variant="ghost" onClick={() => save.mutate('')} disabled={save.isPending}>
            Disconnect
          </Button>
        </div>
      )}
    </div>
  )
}
