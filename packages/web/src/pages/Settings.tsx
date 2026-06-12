// App-wide settings: global default refresh interval.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button, IntervalInputs, totalSeconds } from '../components/fields'
import { useNotify } from '../components/Toast'
import { ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { splitHoursMinutes } from '../lib/format'

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
    </>
  )
}
