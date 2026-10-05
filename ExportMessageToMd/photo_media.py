"""Choose a VK photo copy even when old photos have no dimension metadata."""
from pathlib import Path

# Longest side of VK's named photo copies; used only when dimensions are missing.
PHOTO_SIDES = {"s": 75, "m": 130, "o": 130, "p": 200, "j": 256,
               "q": 320, "r": 510, "x": 604, "y": 807, "z": 1280, "w": 2560}


def photo_sizes(photo):
    def score(size):
        width, height = size.get("width") or 0, size.get("height") or 0
        side = PHOTO_SIDES.get(size.get("type"), 0)
        return (width * height if width > 0 and height > 0 else side * side, side)
    return sorted((s for s in photo.get("sizes", []) if s.get("url")), key=score, reverse=True)


def best_photo_url(photo):
    sizes = photo_sizes(photo)
    return sizes[0]["url"] if sizes else ""


def image_size(path):
    """Read image dimensions without decoding/recompressing the downloaded bytes."""
    try:
        with Path(path).open("rb") as source:
            header = source.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
            if header.startswith((b"GIF87a", b"GIF89a")) and len(header) >= 10:
                return int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little")
            if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                if header[12:16] == b"VP8X" and len(header) >= 30:
                    return 1 + int.from_bytes(header[24:27], "little"), 1 + int.from_bytes(header[27:30], "little")
                if header[12:16] == b"VP8 " and header[23:26] == b"\x9d\x01\x2a":
                    return int.from_bytes(header[26:28], "little") & 0x3fff, int.from_bytes(header[28:30], "little") & 0x3fff
                if header[12:16] == b"VP8L" and header[20:21] == b"\x2f":
                    bits = int.from_bytes(header[21:25], "little")
                    return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
            if not header.startswith(b"\xff\xd8"):
                return None
            source.seek(2)
            while source.tell() < 1024 * 1024:
                if source.read(1) != b"\xff":
                    return None
                marker = source.read(1)
                while marker == b"\xff":
                    marker = source.read(1)
                if not marker or marker in (b"\xd9", b"\xda"):
                    return None
                size = int.from_bytes(source.read(2), "big")
                if size < 2:
                    return None
                if marker[0] in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                    dimensions = source.read(5)
                    if len(dimensions) != 5:
                        return None
                    return int.from_bytes(dimensions[3:5], "big"), int.from_bytes(dimensions[1:3], "big")
                source.seek(size - 2, 1)
    except OSError:
        return None
    return None
