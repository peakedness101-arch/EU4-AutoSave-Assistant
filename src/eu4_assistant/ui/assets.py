from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage, QPixmap

from ..resources import GameResourceResolver


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


def game_logo_pixmap(
    game_dir: str | Path,
    size: tuple[int, int],
    *,
    mod_dir: str | Path | None = None,
) -> QPixmap:
    resources = GameResourceResolver.create(game_dir, mod_dir)
    candidates = [
        resources.resolve_file("gfx/interface/Eu4_logo.dds"),
        resources.resolve_file("gfx/interface/eu4_logo.dds"),
    ]
    for candidate in candidates:
        pixmap = load_pixmap(candidate, size)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


def country_flag_pixmap(
    game_dir: str | Path,
    tag: str,
    size: tuple[int, int] = (72, 72),
    *,
    mod_dir: str | Path | None = None,
) -> QPixmap:
    path = GameResourceResolver.create(game_dir, mod_dir).resolve_file(
        f"gfx/flags/{tag}.tga"
    )
    return load_pixmap(path, size)


def country_shield_pixmap(
    game_dir: str | Path,
    tag: str,
    size: tuple[int, int] = (32, 32),
    *,
    mod_dir: str | Path | None = None,
) -> QPixmap:
    """Compose an EU4 flag with the game's shield mask and frame."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    flag_path = resources.resolve_file(f"gfx/flags/{tag}.tga")
    mask_path = resources.resolve_file("gfx/interface/shield_medium_mask.tga")
    overlay_path = resources.resolve_file("gfx/interface/shield_medium_overlay.dds")
    try:
        with Image.open(mask_path) as opened_mask:
            mask = opened_mask.convert("RGBA")
        with Image.open(overlay_path) as opened_overlay:
            overlay = opened_overlay.convert("RGBA")
        canvas_size = overlay.size
        aperture_size = (
            max(1, round(canvas_size[0] * 0.53)),
            max(1, round(canvas_size[1] * 0.59)),
        )
        aperture_position = (
            (canvas_size[0] - aperture_size[0]) // 2,
            round(canvas_size[1] * 0.125),
        )
        mask_alpha = mask.getchannel("A").resize(
            aperture_size, Image.Resampling.LANCZOS
        )
        if flag_path.is_file():
            with Image.open(flag_path) as opened_flag:
                flag = ImageOps.fit(
                    opened_flag.convert("RGBA"), aperture_size, Image.Resampling.LANCZOS
                )
        else:
            flag = Image.new("RGBA", aperture_size, (42, 67, 82, 255))
            draw = ImageDraw.Draw(flag)
            font = ImageFont.load_default(size=max(8, aperture_size[0] // 4))
            bounds = draw.textbbox((0, 0), tag, font=font)
            draw.text(
                ((aperture_size[0] - (bounds[2] - bounds[0])) / 2,
                 (aperture_size[1] - (bounds[3] - bounds[1])) / 2),
                tag,
                fill=(255, 255, 255, 255),
                font=font,
            )
        flag.putalpha(mask_alpha)
        canvas = Image.new("RGBA", canvas_size)
        canvas.alpha_composite(flag, aperture_position)
        composed = Image.alpha_composite(canvas, overlay)
        composed = ImageOps.contain(composed, size, Image.Resampling.LANCZOS)
        return QPixmap.fromImage(pil_to_qimage(composed))
    except (OSError, UnidentifiedImageError, ValueError):
        return country_flag_pixmap(
            game_dir, tag, size, mod_dir=mod_dir
        )


def game_interface_pixmap(
    game_dir: str | Path,
    candidates: list[str],
    size: tuple[int, int] = (28, 28),
    *,
    mod_dir: str | Path | None = None,
) -> QPixmap:
    """Load the first usable original-game interface image from candidate paths."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    for relative in candidates:
        pixmap = load_pixmap(resources.resolve_file(Path("gfx/interface") / relative), size)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()
