// Port of packages/ui views/_quality.py — image-vs-grid quality hints shared
// by the grid detail page and the upload form.

import type { Device, DeviceProfile, Grid } from './types'

// Thresholds for the source-resolution traffic light. `ratio` is the image's
// effective px/cm divided by the densest member device's px/cm.
export const RES_RATIO_SHARP = 1.0
export const RES_RATIO_SOFT = 0.7
// Aspect drift below this fraction is reported as "no crop".
export const CROP_NEGLIGIBLE = 0.005

export function maxDevicePxcm(grid: Grid, allDevices: Device[], profiles: DeviceProfile[]): number | null {
  const placements = grid.devices ?? []
  if (placements.length === 0) return null
  const deviceById = new Map(allDevices.map((d) => [d.id, d]))
  const profileById = new Map(profiles.map((p) => [p.id, p]))
  const rates: number[] = []
  for (const placement of placements) {
    const device = deviceById.get(placement.device_id)
    if (!device) continue
    const profile = profileById.get(device.device_profile_id)
    if (!profile) continue
    const widthPx = device.display_orientation === 'portrait' ? profile.height : profile.width
    if (placement.width_cm > 0) rates.push(widthPx / placement.width_cm)
  }
  return rates.length ? Math.max(...rates) : null
}

export interface ImageFit {
  imageAspect: number
  canvasAspect: number
  cropPct: number
  cropAxis: 'horizontal' | 'vertical' | 'none'
  effectivePxcm: number
}

// Mirrors the API's cover-fit crop math: the smaller of img_w/grid_w_cm and
// img_h/grid_h_cm becomes the resulting px/cm rate; the overflow axis loses content.
export function imageFit(imageW: number, imageH: number, grid: Grid): ImageFit | null {
  if (!imageW || !imageH) return null
  const gridW = grid.width_cm
  const gridH = grid.height_cm
  const canvasAspect = gridW / gridH
  const imageAspect = imageW / imageH
  if (imageAspect > canvasAspect) {
    const usedW = imageH * canvasAspect
    return {
      imageAspect,
      canvasAspect,
      cropPct: (imageW - usedW) / imageW,
      cropAxis: 'horizontal',
      effectivePxcm: imageH / gridH,
    }
  }
  const usedH = imageW / canvasAspect
  return {
    imageAspect,
    canvasAspect,
    cropPct: (imageH - usedH) / imageH,
    cropAxis: imageAspect < canvasAspect ? 'vertical' : 'none',
    effectivePxcm: imageW / gridW,
  }
}

export type ResolutionBand = 'sharp' | 'soft' | 'upscaled'

export function resolutionBand(ratio: number): { band: ResolutionBand; color: string; glyph: string } {
  if (ratio >= RES_RATIO_SHARP) return { band: 'sharp', color: 'var(--ink-success)', glyph: '✓' }
  if (ratio >= RES_RATIO_SOFT) return { band: 'soft', color: 'var(--ink-warn)', glyph: '⚠' }
  return { band: 'upscaled', color: 'var(--ink-danger)', glyph: '✗' }
}

export function recommendedDims(grid: Grid, maxPxcm: number): { w: number; h: number } {
  return { w: Math.ceil(grid.width_cm * maxPxcm), h: Math.ceil(grid.height_cm * maxPxcm) }
}

export function cropText(fit: ImageFit): string {
  return fit.cropPct < CROP_NEGLIGIBLE ? 'no crop' : `${Math.round(fit.cropPct * 100)}% ${fit.cropAxis} crop`
}
