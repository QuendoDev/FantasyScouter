# src/utils/image_ops.py
import os
from PIL import Image


def centered_crop_and_resize_avatar(image_path: str, logger, target_size=(256, 256)):
    """
    Crops the image to a centered square and resizes it to the target size.

    :param image_path: str, path to the local image file
    :param logger: logging.Logger, logger instance for tracking operations
    :param target_size: tuple, (width, height) for the final output
    """
    if not os.path.exists(image_path):
        logger.warning(f"   > [CROP ERROR] File not found: {image_path}")
        return

    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # --- CROP LOGIC (CENTERED) ---
            # Determine the smallest dimension for the square
            target_dim = min(width, height)

            # Calculate coordinates for a pure Center Crop
            left = (width - target_dim) // 2
            top = (height - target_dim) // 2
            right = left + target_dim
            bottom = top + target_dim

            # Perform Crop
            img_cropped = img.crop((left, top, right, bottom))

            # Resize to target size (High Quality)
            img_final = img_cropped.resize(target_size, Image.Resampling.LANCZOS)

            # Overwrite original
            img_final.save(image_path, optimize=True, quality=90)

            # Log success (Debug level to avoid cluttering info)
            logger.debug(f"   > [CROP] Processed {image_path}")

    except Exception as e:
        logger.warning(f"   > [CROP ERROR] Could not process {image_path}: {e}")