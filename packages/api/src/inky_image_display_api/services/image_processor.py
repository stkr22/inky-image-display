"""Image resize/crop pipeline used by the /api/images/process endpoint.

Lives in the API package because the API is the only callable surface that
produces display-ready bytes — sync workers and other clients no longer
touch this code directly, they POST through the HTTP endpoint instead.
"""

import math
from io import BytesIO

import pillow_heif
from PIL import Image, ImageOps
from PIL.Image import Resampling

# HEIC originals from iPhones are common in the Immich corpus; registering
# the opener once at import time lets PIL.Image.open decode them.
pillow_heif.register_heif_opener()


class ImageProcessingError(Exception):
    """Raised when image processing fails."""


class ImageProcessor:
    """Handles image resizing and cropping for display devices.

    Strategy: Downscale first (preserving aspect ratio to cover target),
    then center-crop to exact dimensions.
    """

    @staticmethod
    def process_for_display(
        image_data: bytes,
        target_width: int,
        target_height: int,
        *,
        upscale: bool = False,
        quality: int = 85,
    ) -> bytes | None:
        """Resize and crop image to fit target dimensions.

        Algorithm:
        1. Calculate scale factor to COVER target (image will be >= target in both dimensions)
        2. Resize using LANCZOS for high quality downscaling
        3. Center-crop to exact target dimensions

        Args:
            image_data: Original image bytes
            target_width: Target width in pixels
            target_height: Target height in pixels
            upscale: Allow upscaling small images (default: False)
            quality: JPEG quality 1-100 (default: 85)

        Returns:
            Processed JPEG image bytes, or None if image is too small and upscale=False

        Raises:
            ImageProcessingError: If image cannot be processed

        """
        try:
            with Image.open(BytesIO(image_data)) as original:
                # Apply EXIF orientation so portrait phone photos (which store
                # landscape pixels + an Orientation tag) are rotated upright
                # before we resize/crop. Without this, the pipeline would
                # center-crop the wrong axis.
                oriented = ImageOps.exif_transpose(original) or original

                # Convert to RGB if needed (for JPEG output), otherwise copy
                processed = oriented.convert("RGB") if oriented.mode in ("RGBA", "P", "LA", "L") else oriented.copy()

                orig_width, orig_height = processed.size

                # Check if image is too small to fit target without upscaling
                if not upscale and (orig_width < target_width or orig_height < target_height):
                    return None

                # Step 1: Calculate scale to COVER target (may overflow one dimension)
                scale_w = target_width / orig_width
                scale_h = target_height / orig_height
                scale = max(scale_w, scale_h)

                # Don't upscale unless explicitly requested
                if not upscale and scale > 1.0:
                    scale = 1.0

                # Round up: cover-fit guarantees both axes are >= target in
                # real arithmetic, but int() truncation can drop the overflow
                # axis 1px below target (e.g. 1599 vs 1600). The center-crop
                # below only trims when current > target, so a floored axis
                # would slip through and the controller rejects the mismatch.
                new_width = math.ceil(orig_width * scale)
                new_height = math.ceil(orig_height * scale)

                # Step 2: Resize with LANCZOS (high quality)
                if scale != 1.0:
                    processed = processed.resize((new_width, new_height), resample=Resampling.LANCZOS)

                # Step 3: Center crop to exact target dimensions
                current_width, current_height = processed.size
                if current_width > target_width or current_height > target_height:
                    left = (current_width - target_width) // 2
                    top = (current_height - target_height) // 2
                    right = left + target_width
                    bottom = top + target_height

                    # Ensure we don't crop beyond image boundaries
                    left = max(0, left)
                    top = max(0, top)
                    right = min(current_width, right)
                    bottom = min(current_height, bottom)

                    processed = processed.crop((left, top, right, bottom))

                # Step 4: Save as JPEG
                output = BytesIO()
                processed.save(output, format="JPEG", quality=quality)
                return output.getvalue()

        except Exception as e:
            raise ImageProcessingError(f"Failed to process image: {e}") from e
