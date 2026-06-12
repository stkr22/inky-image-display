// Client-side cropping via canvas. The cropped JPEG is what gets uploaded,
// so the backend needs no changes and never sees the discarded pixels.

export interface CropRect {
  x: number
  y: number
  width: number
  height: number
}

export interface CroppedResult {
  file: File
  width: number
  height: number
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('Could not decode image'))
    image.src = url
  })
}

// `output` forces exact pixel dimensions (used for e-ink panel targets,
// which require an exact match to be sendable); omitted, the crop keeps
// its native resolution so grid targets retain every available pixel.
export async function cropImage(
  sourceUrl: string,
  crop: CropRect,
  fileName: string,
  output?: { width: number; height: number },
): Promise<CroppedResult> {
  const image = await loadImage(sourceUrl)
  const width = Math.round(output?.width ?? crop.width)
  const height = Math.round(output?.height ?? crop.height)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas 2D context unavailable')
  context.imageSmoothingQuality = 'high'
  context.drawImage(image, crop.x, crop.y, crop.width, crop.height, 0, 0, width, height)

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error('Crop failed'))), 'image/jpeg', 0.92)
  })
  const baseName = fileName.replace(/\.[^.]+$/, '')
  return { file: new File([blob], `${baseName}-crop.jpg`, { type: 'image/jpeg' }), width, height }
}
