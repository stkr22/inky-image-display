// Thin fetch wrapper over the inky-image-display-api REST surface.
// All calls go same-origin to /api/* — the dev server / reverse proxy routes
// them to the API service (see vite.config.ts).

import type {
  AppSettings,
  AuthMe,
  Device,
  DeviceProfile,
  DisplayJob,
  GeminiJob,
  GenerationTask,
  Grid,
  GridContentStatus,
  GridQueueEntry,
  GroupDisplayResult,
  GuestInvite,
  Image,
  ImageGroup,
  ImageStats,
  ImmichRef,
  PromptBlock,
  PromptPreset,
  ScheduleEntry,
  SyncJob,
  SyncJobRun,
} from './types'

const DEVICE_NOT_CONNECTED_DETAIL = 'Device not connected'

export class ApiError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly detail: string | null,
  ) {
    super(detail || `API returned ${statusCode}`)
  }
}

export class DeviceNotConnectedError extends ApiError {}

export function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

interface RequestOptions {
  method?: string
  body?: unknown
  formData?: FormData
  params?: Record<string, string | number | boolean | undefined>
  deviceCommand?: boolean
}

async function requestRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value))
  }
  const init: RequestInit = { method: options.method ?? 'GET' }
  if (options.formData) {
    init.body = options.formData
  } else if (options.body !== undefined) {
    init.body = JSON.stringify(options.body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const response = await fetch(url, init)
  if (!response.ok) {
    // Session expired mid-use (or auth was just enabled): let the auth
    // provider re-check /api/auth/me so the sign-in gate takes over.
    if (response.status === 401) window.dispatchEvent(new Event('inky:unauthorized'))
    const detail = await extractDetail(response)
    if (options.deviceCommand && response.status === 404 && detail === DEVICE_NOT_CONNECTED_DETAIL) {
      throw new DeviceNotConnectedError(response.status, detail)
    }
    throw new ApiError(response.status, detail)
  }
  return response
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await requestRaw(path, options)
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  return (await response.json()) as T
}

async function extractDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.json()
    if (body && typeof body.detail === 'string') return body.detail
    return null
  } catch {
    return null
  }
}

export interface ImageListFilters {
  source_name?: string
  is_portrait?: boolean
  target_grid_id?: string
  solo_only?: boolean
  group_id?: string
  in_group?: boolean
  excluded?: boolean
  search?: string
  limit?: number
  offset?: number
}

// List result carrying the X-Total-Count header so paginated views can
// show "x–y of N" instead of guessing from a short final page.
export interface ImageList {
  items: Image[]
  total: number
}

export const api = {
  // --- Auth / sessions ---
  getAuthMe: () => request<AuthMe>('/api/auth/me'),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  createGuestInvite: () => request<GuestInvite>('/api/auth/guest-invites', { method: 'POST' }),

  // --- Images ---
  listImages: async (filters: ImageListFilters = {}): Promise<ImageList> => {
    const response = await requestRaw('/api/images', { params: { limit: 100, ...filters } })
    const items = (await response.json()) as Image[]
    const total = Number(response.headers.get('X-Total-Count') ?? items.length)
    return { items, total }
  },
  getImage: (id: string) => request<Image>(`/api/images/${id}`),
  getImageStats: () => request<ImageStats>('/api/images/stats'),
  uploadImage: (file: File, metadata: Record<string, unknown>) => {
    const formData = new FormData()
    formData.append('file', file, file.name)
    formData.append('metadata', JSON.stringify(metadata))
    return request<Image>('/api/images', { method: 'POST', formData })
  },
  updateImage: (id: string, body: Record<string, unknown>) =>
    request<Image>(`/api/images/${id}`, { method: 'PUT', body }),
  // E-ink simulation for not-yet-uploaded bytes (upload/crop dialog preview).
  einkPreviewUpload: async (file: Blob, saturation?: number): Promise<Blob> => {
    const formData = new FormData()
    formData.append('file', file, 'preview.jpg')
    if (saturation !== undefined) formData.append('saturation', String(saturation))
    const response = await requestRaw('/api/images/eink-preview', { method: 'POST', formData })
    return response.blob()
  },
  deleteImage: (id: string) => request<void>(`/api/images/${id}`, { method: 'DELETE' }),

  // --- Devices ---
  listDevices: () => request<Device[]>('/api/devices'),
  updateDevice: (deviceId: string, body: Record<string, unknown>) =>
    request<Device>(`/api/devices/${deviceId}`, { method: 'PATCH', body }),
  // fit: 'auto' lets the API cover-crop a copy when the image doesn't match
  // the panel's pixel dimensions; 'exact' (default) gets a 409 instead.
  displayImage: (deviceId: string, imageId: string, fit: 'exact' | 'auto' = 'exact') =>
    request<void>(`/api/devices/${deviceId}/display`, {
      method: 'POST',
      body: { image_id: imageId, fit },
      deviceCommand: true,
    }),
  nextImage: (deviceId: string) =>
    request<{ status: string; image_id: string; title: string | null }>(`/api/devices/${deviceId}/next`, {
      method: 'POST',
      deviceCommand: true,
    }),
  clearDevice: (deviceId: string) =>
    request<void>(`/api/devices/${deviceId}/clear`, { method: 'POST', deviceCommand: true }),

  // --- Device profiles ---
  listDeviceProfiles: () => request<DeviceProfile[]>('/api/device-profiles'),

  // --- Sync jobs (Immich) ---
  listSyncJobs: () => request<SyncJob[]>('/api/sync-jobs'),
  getSyncJob: (id: string) => request<SyncJob>(`/api/sync-jobs/${id}`),
  createSyncJob: (body: Record<string, unknown>) => request<SyncJob>('/api/sync-jobs', { method: 'POST', body }),
  updateSyncJob: (id: string, body: Record<string, unknown>) =>
    request<SyncJob>(`/api/sync-jobs/${id}`, { method: 'PUT', body }),
  deleteSyncJob: (id: string) => request<void>(`/api/sync-jobs/${id}`, { method: 'DELETE' }),
  runSyncJobNow: (id: string) => request<SyncJob>(`/api/sync-jobs/${id}/run-now`, { method: 'POST' }),

  // --- Sync run history (both job types) ---
  listSyncRuns: (params: { job_type?: 'immich' | 'gemini' | 'display'; job_id?: string; limit?: number } = {}) =>
    request<SyncJobRun[]>('/api/sync-runs', { params }),

  // --- Prompt blocks / presets ---
  listPromptBlocks: () => request<PromptBlock[]>('/api/genai/blocks'),
  createPromptBlock: (body: Record<string, unknown>) =>
    request<PromptBlock>('/api/genai/blocks', { method: 'POST', body }),
  updatePromptBlock: (id: string, body: Record<string, unknown>) =>
    request<PromptBlock>(`/api/genai/blocks/${id}`, { method: 'PUT', body }),
  deletePromptBlock: (id: string) => request<void>(`/api/genai/blocks/${id}`, { method: 'DELETE' }),
  listPromptPresets: () => request<PromptPreset[]>('/api/genai/presets'),
  createPromptPreset: (body: Record<string, unknown>) =>
    request<PromptPreset>('/api/genai/presets', { method: 'POST', body }),
  updatePromptPreset: (id: string, body: Record<string, unknown>) =>
    request<PromptPreset>(`/api/genai/presets/${id}`, { method: 'PUT', body }),
  deletePromptPreset: (id: string) => request<void>(`/api/genai/presets/${id}`, { method: 'DELETE' }),

  // --- Gemini jobs ---
  listGeminiJobs: () => request<GeminiJob[]>('/api/genai/jobs'),
  getGeminiJob: (id: string) => request<GeminiJob>(`/api/genai/jobs/${id}`),
  createGeminiJob: (body: Record<string, unknown>) =>
    request<GeminiJob>('/api/genai/jobs', { method: 'POST', body }),
  updateGeminiJob: (id: string, body: Record<string, unknown>) =>
    request<GeminiJob>(`/api/genai/jobs/${id}`, { method: 'PUT', body }),
  deleteGeminiJob: (id: string) => request<void>(`/api/genai/jobs/${id}`, { method: 'DELETE' }),
  runGeminiJobNow: (id: string) => request<GeminiJob>(`/api/genai/jobs/${id}/run-now`, { method: 'POST' }),

  // --- Grids ---
  listGrids: (includeDevices = false) =>
    request<Grid[]>('/api/grids', { params: includeDevices ? { include_devices: true } : {} }),
  getGrid: (id: string) => request<Grid>(`/api/grids/${id}`),
  createGrid: (body: Record<string, unknown>) => request<Grid>('/api/grids', { method: 'POST', body }),
  updateGrid: (id: string, body: Record<string, unknown>) =>
    request<Grid>(`/api/grids/${id}`, { method: 'PUT', body }),
  deleteGrid: (id: string) => request<void>(`/api/grids/${id}`, { method: 'DELETE' }),
  displayGridImage: (gridId: string, imageId: string) =>
    request<Record<string, unknown>>(`/api/grids/${gridId}/display`, { method: 'POST', body: { image_id: imageId } }),
  releaseGrid: (gridId: string) =>
    request<Record<string, unknown>>(`/api/grids/${gridId}/release`, { method: 'POST' }),

  // --- Schedule / settings / generation ---
  getScheduleUpcoming: (limit = 20) => request<ScheduleEntry[]>('/api/schedule/upcoming', { params: { limit } }),
  cronPreview: (cron: string, timezone: string) =>
    request<{ next_runs: string[] }>('/api/schedule/cron-preview', { method: 'POST', body: { cron, timezone } }),
  getWorkerStatus: () => request<{ online: boolean }>('/api/schedule/worker-status'),
  getAppSettings: () => request<AppSettings>('/api/app-settings'),
  updateAppSettings: (body: Record<string, unknown>) =>
    request<AppSettings>('/api/app-settings', { method: 'PUT', body }),
  generateImage: (body: Record<string, unknown>) =>
    request<{ task_id: string; status: string }>('/api/genai/generate', { method: 'POST', body }),
  listGenerationTasks: (limit = 20) => request<GenerationTask[]>('/api/genai/tasks', { params: { limit } }),

  // --- Display jobs (MOTD and future grid content types) ---
  listDisplayJobs: () => request<DisplayJob[]>('/api/display-jobs'),
  createDisplayJob: (body: Record<string, unknown>) =>
    request<DisplayJob>('/api/display-jobs', { method: 'POST', body }),
  getDisplayJob: (id: string) => request<DisplayJob>(`/api/display-jobs/${id}`),
  updateDisplayJob: (id: string, body: Record<string, unknown>) =>
    request<DisplayJob>(`/api/display-jobs/${id}`, { method: 'PUT', body }),
  deleteDisplayJob: (id: string) => request<void>(`/api/display-jobs/${id}`, { method: 'DELETE' }),
  runDisplayJobNow: (id: string) => request<DisplayJob>(`/api/display-jobs/${id}/run-now`, { method: 'POST' }),
  displayJobDisplay: (id: string, groupId?: string) =>
    request<GroupDisplayResult>(`/api/display-jobs/${id}/display`, {
      method: 'POST',
      body: groupId ? { group_id: groupId } : {},
    }),
  listDisplayJobGroups: (id: string, limit = 10) =>
    request<ImageGroup[]>(`/api/display-jobs/${id}/groups`, { params: { limit } }),

  // --- Image groups ---
  listImageGroups: (targetGridId?: string) =>
    request<ImageGroup[]>('/api/image-groups', { params: targetGridId ? { target_grid_id: targetGridId } : {} }),
  createImageGroup: (body: Record<string, unknown>) =>
    request<ImageGroup>('/api/image-groups', { method: 'POST', body }),
  updateImageGroup: (id: string, body: Record<string, unknown>) =>
    request<ImageGroup>(`/api/image-groups/${id}`, { method: 'PUT', body }),
  deleteImageGroup: (id: string, deleteImages = false) =>
    request<void>(`/api/image-groups/${id}`, { method: 'DELETE', params: { delete_images: deleteImages } }),

  // --- Grid content queue ---
  getGridQueue: (gridId: string) => request<GridQueueEntry[]>(`/api/grids/${gridId}/queue`),
  reorderGridQueue: (gridId: string, entries: Array<{ kind: 'group' | 'image'; id: string }>) =>
    request<GridQueueEntry[]>(`/api/grids/${gridId}/queue`, { method: 'PUT', body: { entries } }),
  nextGridContent: (gridId: string) =>
    request<{ status: string }>(`/api/grids/${gridId}/next`, { method: 'POST' }),
  displayGridGroup: (gridId: string, groupId: string) =>
    request<GroupDisplayResult>(`/api/grids/${gridId}/display-group`, {
      method: 'POST',
      body: { group_id: groupId },
    }),
  getGridDisplayStatus: (gridId: string) => request<GridContentStatus>(`/api/grids/${gridId}/display-status`),

  // --- Immich browse proxy (503 when not configured server-side) ---
  listImmichAlbums: () => request<ImmichRef[]>('/api/immich/albums'),
  listImmichPeople: () => request<ImmichRef[]>('/api/immich/people'),
  listImmichTags: () => request<ImmichRef[]>('/api/immich/tags'),
}
