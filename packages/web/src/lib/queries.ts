// Shared query definitions for data that many pages read. One factory per
// resource keeps the cache key and fetcher in lockstep — a page asking for
// grids under a slightly different key would silently fire a second request
// and miss invalidations aimed at the canonical key.

import { queryOptions } from '@tanstack/react-query'
import { api } from './api'

// Profiles only change through migrations/config, so they can stay fresh
// for a while instead of refetching on every page hop.
export const deviceProfilesQuery = queryOptions({
  queryKey: ['device-profiles'],
  queryFn: api.listDeviceProfiles,
  staleTime: 5 * 60_000,
})

// Always fetched with member devices: the few pages that only need names
// share this cache entry instead of issuing a second, device-less request.
// The key lives under ['grids'] so prefix invalidations still reach it.
export const gridsQuery = queryOptions({
  queryKey: ['grids', 'with-devices'],
  queryFn: () => api.listGrids(true),
})

export const devicesQuery = queryOptions({ queryKey: ['devices'], queryFn: api.listDevices })

export const promptPresetsQuery = queryOptions({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })

export const imageGroupsQuery = queryOptions({ queryKey: ['image-groups'], queryFn: () => api.listImageGroups() })
