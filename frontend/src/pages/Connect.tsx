import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ShieldCheck, Users } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router'
import { Button, Card } from '../components/ui'
import { api } from '../lib/api'

/** Opened by the "Connect TalentLens" button on a team's invite page. Always asks first. */
export default function ConnectPage() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const server = sp.get('server') ?? ''
  const code = sp.get('invite') ?? ''
  let host = ''
  try {
    const u = new URL(server)
    if (u.protocol === 'https:' || ['127.0.0.1', 'localhost'].includes(u.hostname)) host = u.host
  } catch {
    /* invalid */
  }
  const valid = !!host && /^[\w-]{20,40}$/.test(code)

  const join = useMutation({
    mutationFn: () => api.joinTeam(`${server.replace(/\/$/, '')}/join/${code}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['connections'] })
    },
  })

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-lg items-center px-4 py-10">
      <Card className="w-full space-y-6 p-8">
        {!valid ? (
          <div className="space-y-2 text-center">
            <h1 className="text-xl font-bold">This link didn't come through correctly</h1>
            <p className="text-[14px] text-muted">Open Settings → Team connections and paste the invite link you received.</p>
            <Button onClick={() => nav('/settings')}>Go to Settings</Button>
          </div>
        ) : join.isSuccess ? (
          <div className="space-y-3 text-center" data-testid="connect-done">
            <CheckCircle2 className="mx-auto size-10 text-ok" />
            <h1 className="text-xl font-bold">You're connected{join.data.name ? `, ${join.data.name}` : ''}</h1>
            <p className="text-[14px] text-muted">
              TalentLens is bringing in your team's connections now. It takes a few minutes the first time; you can keep working.
            </p>
            <div className="flex justify-center gap-2">
              <Button variant="primary" onClick={() => nav('/match')}>
                Match people to a job
              </Button>
              <Button onClick={() => nav('/settings')}>See progress</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-5" data-testid="connect-confirm">
            <div className="space-y-2 text-center">
              <Users className="mx-auto size-10 text-ink" />
              <h1 className="text-xl font-bold">Connect to your team?</h1>
              <p className="text-[14px] text-muted">
                TalentLens will bring in your team's LinkedIn connections from <strong className="text-text">{host}</strong> so you can
                search and match them here. Resumes you add will be shared with the team.
              </p>
            </div>
            <p className="flex items-start gap-2 rounded-md bg-sunken p-3 text-[12.5px] text-muted">
              <ShieldCheck className="mt-0.5 size-4 shrink-0" />
              Only continue if you were expecting an invite to this address. You can disconnect any time in Settings.
            </p>
            {join.isError && <p className="text-[13.5px] text-danger">{(join.error as Error).message}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => nav('/')}>
                Not now
              </Button>
              <Button variant="primary" onClick={() => join.mutate()} disabled={join.isPending} data-testid="connect-confirm-btn">
                {join.isPending ? 'Connecting…' : 'Connect'}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
