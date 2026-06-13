// Mirrors packages/api/src/inky_image_display_api/schemas.py response models.

export interface Image {
  id: string
  source_name: string
  source_id: string | null
  sync_job_name: string | null
  storage_path: string
  source_url: string | null
  title: string | null
  description: string | null
  author: string | null
  original_width: number | null
  original_height: number | null
  is_portrait: boolean
  display_duration_seconds: number
  priority: number
  last_displayed_at: string | null
  expires_at: string | null
  created_at: string
  tags: string | null
  target_grid_id: string | null
}

export interface DeviceProfile {
  id: string
  key: string
  name: string
  width: number
  height: number
  physical_width_cm: number
  physical_height_cm: number
  model: string
  is_default: boolean
}

export interface ImageSummary {
  id: string
  storage_path: string
  title: string | null
}

export interface Device {
  id: string
  device_id: string
  room: string | null
  device_profile_id: string
  display_orientation: 'landscape' | 'portrait'
  is_online: boolean
  current_image_id: string | null
  claimed_by_grid_id: string | null
  displayed_since: string | null
  scheduled_next_at: string
  last_seen: string
  // Most recent display-refresh outcome from the device ack. null = no ack yet;
  // false flags a stuck/failed refresh even while the device is online.
  last_refresh_ok: boolean | null
  last_error: string | null
  last_error_at: string | null
  refresh_interval_seconds: number | null
  current_image: ImageSummary | null
}

export interface SyncJob {
  id: string
  name: string
  is_active: boolean
  target_device_profile_id: string
  orientation: string | null
  strategy: string
  query: string | null
  count: number
  random_pick: boolean
  overfetch_multiplier: number
  album_ids: string[] | null
  person_ids: string[] | null
  tag_ids: string[] | null
  is_favorite: boolean | null
  city: string | null
  state: string | null
  country: string | null
  taken_after: string | null
  taken_before: string | null
  rating: number | null
  created_at: string
  updated_at: string
}

export interface PromptBlock {
  id: string
  kind: string
  name: string
  text: string
  is_default: boolean
}

export interface PromptPreset {
  id: string
  name: string
  style_block_id: string
  palette_block_id: string
  legibility_block_id: string
  composition_block_id: string
  background_block_id: string
  model_name: string
  is_default: boolean
}

export interface GeminiJob {
  id: string
  name: string
  is_active: boolean
  target_device_profile_id: string
  prompt_preset_id: string
  orientation: string
  subjects: string[]
  images_per_subject: number
  retention_days: number | null
  created_at: string
  updated_at: string
}

export interface GridPlacement {
  grid_id: string
  device_id: string
  bottom_left_x_cm: number
  bottom_left_y_cm: number
  width_cm: number
  height_cm: number
}

export interface Grid {
  id: string
  name: string
  width_cm: number
  height_cm: number
  current_image_id: string | null
  displayed_since: string | null
  scheduled_next_at: string
  refresh_interval_seconds: number | null
  devices: GridPlacement[] | null
}

export interface ScheduleEntry {
  kind: 'device' | 'grid'
  id: string
  name: string
  scheduled_next_at: string
  refresh_interval_seconds: number | null
  effective_interval_seconds: number
}

export interface AppSettings {
  default_refresh_seconds: number
}

export interface ImageStats {
  total: number
  by_source: Record<string, number>
}

export interface GenerationTask {
  task_id: string
  subject: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  created_at: string
  finished_at: string | null
  image_id: string | null
  error: string | null
  detail: string | null
}

// Immich entity reference (album, person or tag) from the API's browse proxy.
export interface ImmichRef {
  id: string
  name: string
}

export const PROMPT_BLOCK_KINDS = ['style', 'palette', 'legibility', 'composition', 'background'] as const
export type PromptBlockKind = (typeof PROMPT_BLOCK_KINDS)[number]

export const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash-image'

// Width snaps server-side to 240/480/960; thumbnails are generated lazily
// and cached in the bucket. Omit width for the full original.
export function mediaUrl(storagePath: string, width?: 240 | 480 | 960): string {
  return width ? `/media/${storagePath}?w=${width}` : `/media/${storagePath}`
}

export function imageTitle(image: Pick<Image, 'title' | 'storage_path'>): string {
  return image.title || image.storage_path.split('/').pop() || image.storage_path
}
