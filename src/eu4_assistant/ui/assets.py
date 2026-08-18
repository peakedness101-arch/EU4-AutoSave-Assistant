from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage, QPixmap


def pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    return QImage(
        raw,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()


def load_pixmap(path: str | Path, size: tuple[int, int]) -> QPixmap:
    source = Path(path)
    if not source.is_file():
        return QPixmap()
    try:
        with Image.open(source) as opened:
            image = ImageOps.contain(
                opened.convert("RGBA"), size, Image.Resampling.LANCZOS
            )
            return QPixmap.fromImage(pil_to_qimage(image))
    except (OSError, UnidentifiedImageError):
        return QPixmap()


def game_logo_pixmap(game_dir: str | Path, size: tuple[int, int]) -> QPixmap:
    candidates = [
        Path(game_dir) / "gfx" / "interface" / "Eu4_logo.dds",
        Path(game_dir) / "gfx" / "interface" / "eu4_logo.dds",
    ]
    for candidate in candidates:
        pixmap = load_pixmap(candidate, size)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


def country_flag_pixmap(
    game_dir: str | Path, tag: str, size: tuple[int, int] = (72, 72)
) -> QPixmap:
    return load_pixmap(Path(game_dir) / "gfx" / "flags" / f"{tag}.tga", size)


def game_interface_pixmap(
    game_dir: str | Path,
    candidates: list[str],
    size: tuple[int, int] = (28, 28),
) -> QPixmap:
    """Load the first usable original-game interface image from candidate paths."""
    root = Path(game_dir) / "gfx" / "interface"
    for relative in candidates:
        pixmap = load_pixmap(root / relative, size)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()
