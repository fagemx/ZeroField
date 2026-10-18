"""Bounded uploads with format checks; assets are never executable content."""
import io

MAX_BYTES = 64 * 1024 * 1024


class MediaError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validate(data, content_type):
    if not data:
        raise MediaError(400, "The media file is empty.")
    if len(data) > MAX_BYTES:
        raise MediaError(413, "Media files must be 64 MB or smaller.")
    claimed = str(content_type or "").split(";", 1)[0].lower().strip()
    actual = None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        actual = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        actual = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        actual = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        actual = "image/webp"
    elif len(data) >= 16 and data[4:8] == b"ftyp":
        actual = "audio/mp4" if claimed == "audio/mp4" else "video/mp4"
    elif data.startswith(b"\x1aE\xdf\xa3"):
        actual = "audio/webm" if claimed == "audio/webm" else "video/webm"
    elif data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        actual = "audio/wav"
    elif data.startswith(b"OggS"):
        actual = "audio/ogg"
    elif data.startswith(b"fLaC"):
        actual = "audio/flac"
    elif data.startswith(b"ID3") or len(data) > 2 and data[0] == 255 and data[1] & 0xE0 == 0xE0:
        actual = "audio/mpeg"
    aliases = {"audio/x-wav": "audio/wav", "audio/mp3": "audio/mpeg", "audio/x-flac": "audio/flac"}
    if not actual or claimed not in ("", "application/octet-stream", actual) and aliases.get(claimed) != actual:
        raise MediaError(415, "Media content does not match its format. Supported formats: PNG/JPEG/GIF/WebP, MP4/WebM, MP3/WAV/OGG/FLAC.")
    if actual.startswith("image/"):
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 40_000_000:
                    raise MediaError(413, "Images support at most 40 million pixels.")
                image.verify()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            raise MediaError(400, "The image file is damaged.") from exc
    return actual
