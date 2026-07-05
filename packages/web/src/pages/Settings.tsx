// App-wide settings: global default refresh interval, guest access.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Dialog } from '../components/Dialog'
import { Button, IntervalInputs, totalSeconds } from '../components/fields'
import { useNotify } from '../components/Toast'
import { ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime, splitHoursMinutes } from '../lib/format'
import type { GuestInvite } from '../lib/types'

export function Settings() {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: settings, isPending, error } = useQuery({ queryKey: ['app-settings'], queryFn: api.getAppSettings })

  const [hours, setHours] = useState<number | ''>(0)
  const [minutes, setMinutes] = useState<number | ''>(0)

  useEffect(() => {
    if (!settings) return
    const [h, m] = splitHoursMinutes(settings.default_refresh_seconds)
    setHours(h)
    setMinutes(m)
  }, [settings])

  const save = async () => {
    const total = totalSeconds(hours, minutes)
    if (total <= 0) {
      notify('Pick at least 1 minute.', 'warning')
      return
    }
    try {
      await api.updateAppSettings({ default_refresh_seconds: total })
    } catch (err) {
      notify(`Update failed: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative')
      return
    }
    notify('Default refresh interval updated', 'positive')
    queryClient.invalidateQueries({ queryKey: ['app-settings'] })
  }

  if (isPending) return <Spinner />
  if (error) return <ErrorNote>Failed to load settings.</ErrorNote>

  return (
    <>
      <PageHeader eyebrow="Configuration" title="Settings" />
      <span className="ink-small">
        Operator-tunable values. Changes apply on the next refresh tick — devices already scheduled keep their current
        slot.
      </span>

      <div className="ink-card" style={{ maxWidth: 480, padding: 20 }}>
        <h3 className="ink-h3">Default refresh interval</h3>
        <span className="ink-small">
          Used for devices and grids that have 'Use default interval' enabled. Range: 1 minute to 1 week.
        </span>
        <IntervalInputs hours={hours} minutes={minutes} onHours={setHours} onMinutes={setMinutes} />
        <div className="row w-full justify-end">
          <Button primary icon="save" onClick={save}>
            Save
          </Button>
        </div>
      </div>

      <GuestAccessCard />
    </>
  )
}

// Guest invites: one QR code / link mints restricted guest sessions (browse
// + GenAI only) for everyone who opens it until the invite expires — no
// identity-provider account needed for party guests.
function GuestAccessCard() {
  const notify = useNotify()
  const [invite, setInvite] = useState<GuestInvite | null>(null)
  const [creating, setCreating] = useState(false)

  const createInvite = async () => {
    setCreating(true)
    try {
      setInvite(await api.createGuestInvite())
    } catch (err) {
      notify(`Could not create invite: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative')
    } finally {
      setCreating(false)
    }
  }

  const copyLink = async () => {
    if (!invite) return
    try {
      await navigator.clipboard.writeText(invite.url)
      notify('Invite link copied', 'positive')
    } catch {
      notify('Copy failed — select the link text manually.', 'warning')
    }
  }

  return (
    <div className="ink-card" style={{ maxWidth: 480, padding: 20 }}>
      <h3 className="ink-h3">Guest access</h3>
      <span className="ink-small">
        Create a short-lived invite link for visitors. Anyone opening it can browse images and generate new ones, but
        cannot change devices, jobs or settings. Share the QR code or the link itself.
      </span>
      <div className="row w-full justify-end">
        <Button primary icon="qr_code_2" onClick={createInvite} disabled={creating}>
          {creating ? 'Creating…' : 'Create invite link'}
        </Button>
      </div>

      <Dialog open={invite !== null} onClose={() => setInvite(null)} style={{ maxWidth: 420 }}>
        {invite && (
          <>
            <h3 className="ink-h3">Guest invite</h3>
            <div className="w-full" style={{ display: 'grid', placeItems: 'center' }}>
              <img
                src={`data:image/png;base64,${invite.qr_png_base64}`}
                alt="Guest invite QR code"
                style={{ width: 240, height: 240, imageRendering: 'pixelated', borderRadius: 8, background: '#fff' }}
              />
            </div>
            <span className="ink-small" style={{ wordBreak: 'break-all', userSelect: 'all' }}>
              {invite.url}
            </span>
            <span className="ink-small">Valid until {formatDatetime(invite.expires_at)}.</span>
            <div className="row justify-end gap-2 w-full">
              <Button flat onClick={() => setInvite(null)}>
                Close
              </Button>
              <Button primary icon="content_copy" onClick={copyLink}>
                Copy link
              </Button>
            </div>
          </>
        )}
      </Dialog>
    </div>
  )
}
