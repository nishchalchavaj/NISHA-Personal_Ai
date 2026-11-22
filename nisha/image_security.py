"""Decode only raster formats and strip active/polyglot metadata before display."""

import io

from PIL import Image, ImageOps

from nisha.errors import NishaError

FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".gif": "GIF",
    ".webp": "WEBP",
    ".bmp": "BMP",
}


def passive_image(data, suffix=None):
    try:
        if not data or len(data) > 25_000_000:
            raise NishaError("Choose an image of at most 25 MB.")
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in set(FORMATS.values()) or (
                suffix and FORMATS.get(suffix) != source.format
            ):
                raise NishaError("Image content does not match an allowed raster image format.")
            if source.width * source.height > 32_000_000:
                raise NishaError("Resize this image below 32 megapixels before displaying it.")
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.thumbnail((2048, 2048))
            oriented = ImageOps.exif_transpose(source)
            image = oriented.convert(
                "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
            )
            image.info.clear()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise NishaError("This is not a safely readable raster image.") from exc
