"""Generate committed Keivotos derivatives from the angular avatar mark."""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "assets" / "branding" / "keivotos"
VECTOR_MASTER = BRAND_DIR / "source" / "keivotos-angular-logo.svg"
RASTER_MASTER = BRAND_DIR / "keivotos-logo.png"
MODULE_MASTER = ROOT / "assets" / "branding" / "danbooru" / "icon.svg"
MODULE_PROFILE_MASTER = ROOT / "assets" / "branding" / "danbooru" / "profile-avatar.svg"
PUBLIC_DIR = ROOT / "frontend" / "public"
PACKAGING_ASSETS = ROOT / "packaging" / "windows" / "assets"

NAVY = "#0b0c17"
INK = "#f5f4ff"
MUTED = "#b7b4c9"
CYAN = "#55d9ff"
VIOLET = "#9d6cff"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def fitted_mark(master: Image.Image, size: int, padding_ratio: float = 0.10) -> Image.Image:
    alpha = master.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise RuntimeError(f"The master mark has no visible pixels: {RASTER_MASTER}")
    mark = master.crop(box)
    inner = round(size * (1 - 2 * padding_ratio))
    mark.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return canvas


def gradient(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, NAVY)
    pixels = image.load()
    start = (11, 12, 23)
    end = (24, 19, 48)
    for y in range(height):
        mix = y / max(1, height - 1)
        row = tuple(round(start[i] * (1 - mix) + end[i] * mix) for i in range(3))
        for x in range(width):
            pixels[x, y] = row
    return image.convert("RGBA")


def wordmark(master: Image.Image) -> Image.Image:
    image = Image.new("RGBA", (1600, 420), (0, 0, 0, 0))
    image.alpha_composite(fitted_mark(master, 360, 0.06), (18, 30))
    draw = ImageDraw.Draw(image)
    draw.text((400, 82), "Keivotos", font=font(164, bold=True), fill=INK)
    draw.text((410, 267), "Your archives, kept close.", font=font(42), fill=MUTED)
    return image


def social_preview(master: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = gradient(size)
    width, height = size
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((width - 240, -180, width + 300, 360), fill=(89, 217, 255, 18))
    glow_draw.ellipse((width - 160, height - 120, width + 280, height + 320), fill=(157, 108, 255, 18))
    image = Image.alpha_composite(image, glow)
    draw = ImageDraw.Draw(image)
    mark_size = min(round(height * 0.74), 520)
    image.alpha_composite(fitted_mark(master, mark_size, 0.03), (70, (height - mark_size) // 2))
    text_x = 70 + mark_size + 48
    draw.text((text_x, round(height * 0.28)), "Keivotos", font=font(round(height * 0.17), bold=True), fill=INK)
    draw.text((text_x + 8, round(height * 0.53)), "A local-first home for the media", font=font(round(height * 0.046)), fill=MUTED)
    draw.text((text_x + 8, round(height * 0.61)), "you choose to preserve.", font=font(round(height * 0.046)), fill=MUTED)
    draw.rounded_rectangle((text_x + 8, round(height * 0.76), text_x + 142, round(height * 0.765) + 8), radius=4, fill=CYAN)
    draw.rounded_rectangle((text_x + 154, round(height * 0.76), text_x + 288, round(height * 0.765) + 8), radius=4, fill=VIOLET)
    return image.convert("RGB")


def main() -> None:
    if not VECTOR_MASTER.is_file():
        raise SystemExit(f"Missing canonical vector brand mark: {VECTOR_MASTER}")
    if not RASTER_MASTER.is_file():
        raise SystemExit(f"Missing transparent raster master: {RASTER_MASTER}")
    if not MODULE_MASTER.is_file():
        raise SystemExit(f"Missing Danbooru module mark: {MODULE_MASTER}")
    for directory in (BRAND_DIR, PUBLIC_DIR, PACKAGING_ASSETS):
        directory.mkdir(parents=True, exist_ok=True)

    master = Image.open(RASTER_MASTER).convert("RGBA")
    icons: dict[int, Image.Image] = {}
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        icon = fitted_mark(master, size)
        icons[size] = icon
        icon.save(BRAND_DIR / f"keivotos-icon-{size}.png", optimize=True)

    icons[256].save(
        BRAND_DIR / "keivotos.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    shutil.copy2(BRAND_DIR / "keivotos.ico", PACKAGING_ASSETS / "keivotos.ico")
    shutil.copy2(BRAND_DIR / "keivotos-icon-512.png", PUBLIC_DIR / "keivotos-logo.png")
    shutil.copy2(BRAND_DIR / "keivotos-icon-64.png", PUBLIC_DIR / "favicon.png")
    shutil.copy2(MODULE_MASTER, PUBLIC_DIR / "logo.svg")
    shutil.copy2(VECTOR_MASTER, PUBLIC_DIR / "favicon.svg")
    shutil.copy2(MODULE_PROFILE_MASTER, PUBLIC_DIR / "profile-avatar.svg")

    wordmark(master).save(BRAND_DIR / "keivotos-wordmark.png", optimize=True)
    social_preview(master, (1600, 500)).save(BRAND_DIR / "keivotos-banner.png", optimize=True)
    social = social_preview(master, (1280, 640))
    social.save(BRAND_DIR / "keivotos-social-preview.png", optimize=True)

if __name__ == "__main__":
    main()
