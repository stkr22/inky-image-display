// Landing page: hero band + bento dashboard. All tiles fetch in parallel via
// react-query, so the dashboard renders progressively instead of blocking on
// the slowest call (an improvement over the sequential NiceGUI version).

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { imageTitle, mediaUrl, type Device, type Image } from '../lib/types'
import { Icon } from '../components/fields'
import { Badge, BentoGrid, Stat, Tile } from '../components/ui'

export function Landing() {
  return (
    <>
      <Hero />
      <BentoGrid>
        <ImagesTile />
        <DevicesTile />
        <JobsTile />
        <RecentActivityTile />
        <QuickActionsTile />
      </BentoGrid>
    </>
  )
}

function Hero() {
  return (
    <div className="col gap-4 w-full" style={{ padding: '16px 0 8px 0' }}>
      <span className="ink-eyebrow">Inky Image Display</span>
      <h1 className="ink-h1">Your photos, on paper that never sleeps.</h1>
      <p className="ink-body ink-muted" style={{ maxWidth: 640, margin: 0 }}>
        A quiet wall of e-paper, refreshed automatically from your library. Pick a device, push an image, or let
        your sync rules do the work.
      </p>
      <div className="row gap-2" style={{ marginTop: 8 }}>
        <Link to="/displays" className="ink-btn ink-btn-primary">
          <Icon name="devices" />
          Open device wall
        </Link>
        <Link to="/images" className="ink-btn ink-btn-ghost">
          <Icon name="image" />
          Browse images
        </Link>
      </div>
    </div>
  )
}

function ImagesTile() {
  const { data: stats } = useQuery({ queryKey: ['images', 'stats'], queryFn: api.getImageStats })
  const manual = stats?.by_source['manual'] ?? 0
  const immich = stats?.by_source['immich'] ?? 0
  return (
    <Tile span="col-span-4" to="/images">
      <Stat label="Images" value={stats?.total ?? 0} hint={`${manual} manual · ${immich} immich`} />
    </Tile>
  )
}

function JobsTile() {
  const { data: immich } = useQuery({ queryKey: ['sync-jobs'], queryFn: api.listSyncJobs })
  const { data: gemini } = useQuery({ queryKey: ['gemini-jobs'], queryFn: api.listGeminiJobs })
  const total = (immich?.length ?? 0) + (gemini?.length ?? 0)
  const active = (immich?.filter((j) => j.is_active).length ?? 0) + (gemini?.filter((j) => j.is_active).length ?? 0)
  return (
    <Tile span="col-span-4" to="/jobs">
      <Stat label="Jobs" value={`${active}/${total}`} hint={`Immich ${immich?.length ?? 0} · Gemini ${gemini?.length ?? 0}`} />
    </Tile>
  )
}

function DevicesTile() {
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })
  const online = devices?.filter((d) => d.is_online).length ?? 0
  return (
    <Tile span="col-span-8" rowSpan="row-span-2">
      <div className="row w-full items-baseline justify-between">
        <div className="col gap-0">
          <span className="ink-eyebrow">Wall</span>
          <h3 className="ink-h3">Devices</h3>
        </div>
        <span className="ink-small">
          {online}/{devices?.length ?? 0} online
        </span>
      </div>
      {devices && devices.length === 0 && <span className="ink-small">No devices registered yet.</span>}
      <div
        className="w-full gap-3"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', marginTop: 4 }}
      >
        {devices?.slice(0, 6).map((device) => <MiniDevice key={device.id} device={device} />)}
      </div>
    </Tile>
  )
}

function MiniDevice({ device }: { device: Device }) {
  const image = device.current_image
  return (
    <Link to="/displays" className="ink-device-card">
      {image ? (
        <img className="ink-device-image" src={mediaUrl(image.storage_path, 480)} loading="lazy" alt={imageTitle(image)} />
      ) : (
        <div className="ink-device-image-empty">
          <span className="ink-small">—</span>
        </div>
      )}
      <div className="col gap-1" style={{ padding: 12 }}>
        <div className="row items-center justify-between">
          <span style={{ fontSize: 14, fontWeight: 500 }}>{device.device_id}</span>
          <Badge tone={device.is_online ? 'ok' : 'muted'} />
        </div>
        <span className="ink-small truncate">{device.room || '—'}</span>
      </div>
    </Link>
  )
}

function RecentActivityTile() {
  const { data: images } = useQuery({ queryKey: ['images', 'recent'], queryFn: () => api.listImages({ limit: 12 }) })
  const recent = [...(images ?? [])]
    .sort((a, b) =>
      (b.last_displayed_at || b.created_at || '').localeCompare(a.last_displayed_at || a.created_at || ''),
    )
    .slice(0, 6)
  return (
    <Tile span="col-span-12">
      <div className="row w-full items-baseline justify-between">
        <div className="col gap-0">
          <span className="ink-eyebrow">Recent</span>
          <h3 className="ink-h3">Last shown</h3>
        </div>
        <Link to="/images" className="ink-nav-link">
          All images →
        </Link>
      </div>
      {recent.length === 0 ? (
        <span className="ink-small">No images yet. Upload one to get started.</span>
      ) : (
        <div
          className="w-full gap-3"
          style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))' }}
        >
          {recent.map((image) => <Thumb key={image.id} image={image} />)}
        </div>
      )}
    </Tile>
  )
}

function Thumb({ image }: { image: Image }) {
  return (
    <Link to={`/images/${image.id}`} className="ink-thumb">
      <img src={mediaUrl(image.storage_path, 480)} loading="lazy" alt={imageTitle(image)} />
      <span className="ink-thumb-caption">{imageTitle(image)}</span>
    </Link>
  )
}

function QuickActionsTile() {
  const actions = [
    { icon: 'upload', title: 'Upload an image', hint: 'Add a photo to your library', to: '/images/new' },
    { icon: 'auto_awesome', title: 'Generate an image', hint: 'One-off AI image via Gemini', to: '/genai' },
    { icon: 'sync', title: 'New sync job', hint: 'Pull from Immich automatically', to: '/sync-jobs/new' },
    { icon: 'devices', title: 'Manage devices', hint: 'Choose what each display shows', to: '/displays' },
  ]
  return (
    <Tile span="col-span-12">
      <div className="col gap-0">
        <span className="ink-eyebrow">Get started</span>
        <h3 className="ink-h3">Quick actions</h3>
      </div>
      <div className="row w-full gap-3 wrap">
        {actions.map((action) => (
          <Link key={action.to + action.title} to={action.to} className="ink-action-card">
            <span className="ink-action-icon">
              <Icon name={action.icon} />
            </span>
            <div className="col gap-0 flex-1">
              <span style={{ fontSize: 14, fontWeight: 500 }}>{action.title}</span>
              <span className="ink-small truncate">{action.hint}</span>
            </div>
          </Link>
        ))}
      </div>
    </Tile>
  )
}
