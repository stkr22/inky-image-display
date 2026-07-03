// Thin fetch wrapper over the inky-image-display-api REST surface.
// All calls go same-origin to /api/* — the dev server / reverse proxy routes
// them to the API service (see vite.config.ts).

import type {
  AppSettings,
  Device,
  DeviceProfile,
  GeminiJob,
  GenerationTask,
  Grid,
  GridPlacement,
  Image,
  ImageStats,
  ImmichRef,
  MotdConfig,
  MotdDisplayResult,
  MotdMessage,
  MotdStatus,
  PromptBlock,
  PromptPreset,
  ScheduleEntry,
  SyncJob,
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

interface RequestOptions {
  method?: string
  body?: unknown
  formData?: FormData
  params?: Record<string, string | number | boolean | undefined>
  deviceCommand?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    const detail = await extractDetail(response)
    if (options.deviceCommand && response.status === 404 && detail === DEVICE_NOT_CONNECTED_DETAIL) {
      throw new DeviceNotConnectedError(response.status, detail)
    }
    throw new ApiError(response.status, detail)
  }
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
  search?: string
  limit?: number
  offset?: number
}

export const api = {
  // --- Images ---
  listImages: (filters: ImageListFilters = {}) =>
    request<Image[]>('/api/images', { params: { limit: 100, ...filters } }),
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
  deleteImage: (id: string) => request<void>(`/api/images/${id}`, { method: 'DELETE' }),

  // --- Devices ---
  listDevices: () => request<Device[]>('/api/devices'),
  updateDevice: (deviceId: string, body: Record<string, unknown>) =>
    request<Device>(`/api/devices/${deviceId}`, { method: 'PATCH', body }),
  displayImage: (deviceId: string, imageId: string) =>
    request<void>(`/api/devices/${deviceId}/display`, {
      method: 'POST',
      body: { image_id: imageId },
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

  // --- Grids ---
  listGrids: (includeDevices = false) =>
    request<Grid[]>('/api/grids', { params: includeDevices ? { include_devices: true } : {} }),
  getGrid: (id: string) => request<Grid>(`/api/grids/${id}`),
  createGrid: (body: Record<string, unknown>) => request<Grid>('/api/grids', { method: 'POST', body }),
  updateGrid: (id: string, body: Record<string, unknown>) =>
    request<Grid>(`/api/grids/${id}`, { method: 'PUT', body }),
  deleteGrid: (id: string) => request<void>(`/api/grids/${id}`, { method: 'DELETE' }),
  addDeviceToGrid: (gridId: string, body: Record<string, unknown>) =>
    request<GridPlacement>(`/api/grids/${gridId}/devices`, { method: 'POST', body }),
  updateDevicePlacement: (gridId: string, deviceId: string, body: Record<string, unknown>) =>
    request<GridPlacement>(`/api/grids/${gridId}/devices/${deviceId}`, { method: 'PUT', body }),
  removeDeviceFromGrid: (gridId: string, deviceId: string) =>
    request<void>(`/api/grids/${gridId}/devices/${deviceId}`, { method: 'DELETE' }),
  displayGridImage: (gridId: string, imageId: string) =>
    request<Record<string, unknown>>(`/api/grids/${gridId}/display`, { method: 'POST', body: { image_id: imageId } }),
  releaseGrid: (gridId: string) =>
    request<Record<string, unknown>>(`/api/grids/${gridId}/release`, { method: 'POST' }),

  // --- Schedule / settings / generation ---
  getScheduleUpcoming: (limit = 20) => request<ScheduleEntry[]>('/api/schedule/upcoming', { params: { limit } }),
  getAppSettings: () => request<AppSettings>('/api/app-settings'),
  updateAppSettings: (body: Record<string, unknown>) =>
    request<AppSettings>('/api/app-settings', { method: 'PUT', body }),
  generateImage: (body: Record<string, unknown>) =>
    request<{ task_id: string; status: string }>('/api/genai/generate', { method: 'POST', body }),
  listGenerationTasks: (limit = 20) => request<GenerationTask[]>('/api/genai/tasks', { params: { limit } }),

  // --- Message of the day ---
  getMotdConfig: () => request<MotdConfig>('/api/motd/config'),
  updateMotdConfig: (body: Record<string, unknown>) =>
    request<MotdConfig>('/api/motd/config', { method: 'PUT', body }),
  motdGenerate: () => request<{ task_id: string; status: string }>('/api/motd/generate', { method: 'POST' }),
  motdDisplay: (messageId?: string) =>
    request<MotdDisplayResult>('/api/motd/display', {
      method: 'POST',
      body: messageId ? { message_id: messageId } : {},
    }),
  motdRelease: () => request<{ status: string }>('/api/motd/release', { method: 'POST' }),
  getMotdStatus: () => request<MotdStatus>('/api/motd/status'),
  getLatestMotdMessage: () => request<MotdMessage | null>('/api/motd/messages/latest'),
  listMotdMessages: (limit = 10) => request<MotdMessage[]>('/api/motd/messages', { params: { limit } }),

  // --- Immich browse proxy (503 when not configured server-side) ---
  listImmichAlbums: () => request<ImmichRef[]>('/api/immich/albums'),
  listImmichPeople: () => request<ImmichRef[]>('/api/immich/people'),
  listImmichTags: () => request<ImmichRef[]>('/api/immich/tags'),
}
