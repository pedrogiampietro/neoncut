"""Gera o icone do NeonCut (assets/icon.png, assets/icon.ico) e as imagens do instalador.

Silhueta de pessoa em neon (magenta -> ciano) sobre um quadrado escuro arredondado,
com um corte diagonal: a ideia de "recortar voce do fundo".
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 1024
MAGENTA = np.float32((1.0, 0.15, 0.8))
VIOLET = np.float32((0.55, 0.3, 1.0))
CYAN = np.float32((0.1, 0.85, 1.0))


def layer(draw_fn, size=S):
    img = Image.new("L", (size * 2, size * 2), 0)
    draw_fn(ImageDraw.Draw(img), 2)
    return np.asarray(img.resize((size, size), Image.LANCZOS), np.float32) / 255


def gradient(size=S):
    """Diagonal magenta -> violeta -> ciano."""
    t = (np.add.outer(np.arange(size), np.arange(size)) / (2 * size - 2)).astype(np.float32)[..., None]
    first = MAGENTA * (1 - t * 2) + VIOLET * (t * 2)
    second = VIOLET * (2 - t * 2) + CYAN * (t * 2 - 1)
    return np.where(t < 0.5, first, second)


def render(size=S):
    k = size / S
    # fundo: quadrado arredondado escuro com leve brilho violeta no topo
    tile = layer(lambda d, s: d.rounded_rectangle([40 * k * s, 40 * k * s, (S - 40) * k * s, (S - 40) * k * s],
                                                  210 * k * s, fill=255), size)
    yy = np.linspace(0, 1, size, dtype=np.float32)[:, None, None]
    bg = np.float32((0.07, 0.06, 0.11)) * (1 - yy) + np.float32((0.03, 0.025, 0.05)) * yy
    bg = bg + np.exp(-((yy - 0.15) ** 2) / 0.05) * VIOLET * 0.08

    # silhueta preenchida (cabeca + ombros), cortada embaixo pela borda do "quadro"
    def person(d, s):
        d.ellipse([377 * k * s, 215 * k * s, 647 * k * s, 485 * k * s], fill=255)
        d.chord([232 * k * s, 535 * k * s, 792 * k * s, 1095 * k * s], 180, 360, fill=255)

    body = layer(person, size)
    bottom = int(810 * k)
    body[bottom:] = 0

    # contorno tracejado de selecao em volta (o "recorte"), com folga da silhueta
    sil = (body > 0.5).astype(np.uint8)
    grow = lambda r: cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    ring = (grow(int(52 * k)) - grow(int(38 * k))).astype(np.float32)
    ring[bottom + int(52 * k):] = 0
    yy_, xx_ = np.mgrid[:size, :size]
    dashes = (np.sin((xx_ + yy_) / (22 * k)) > -0.2).astype(np.float32)
    outline = cv2.GaussianBlur(ring * dashes, (0, 0), max(0.6, 1.2 * k))

    grad = gradient(size)
    fill = body[..., None] * grad
    emissive = fill * 0.9 + outline[..., None] * np.float32((1, 1, 1))
    glow = sum(cv2.GaussianBlur(emissive, (0, 0), sig * k) * g for sig, g in ((10, 0.5), (40, 0.5), (110, 0.35)))
    img = bg * (1 - body[..., None]) + glow + fill * 0.75 + outline[..., None] * 0.8
    peak = img.max(axis=2, keepdims=True)
    img = img * ((1 - np.exp(-peak * 1.8)) / np.maximum(peak, 1e-6))
    rgba = np.dstack([np.clip(img, 0, 1), tile]) * 255
    return Image.fromarray(rgba.astype(np.uint8), "RGBA")


def wizard_images(icon):
    """Imagens do instalador Inno Setup (lateral 164x314 e pequena 55x58, em escala 2x)."""
    w, h = 328, 628
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    side = np.float32((0.06, 0.05, 0.1)) * (1 - y) + np.float32((0.02, 0.02, 0.04)) * y
    side = side + np.exp(-((x - 0.5) ** 2 + (y - 0.35) ** 2) / 0.04) * VIOLET * 0.35
    side = Image.fromarray((np.clip(side, 0, 1) * 255).astype(np.uint8), "RGB")
    logo = icon.resize((230, 230), Image.LANCZOS)
    side.paste(logo, ((w - 230) // 2, 110), logo)
    side.save(ASSETS / "wizard.bmp")
    small = Image.new("RGB", (110, 116), (255, 255, 255))
    logo = icon.resize((100, 100), Image.LANCZOS)
    small.paste(logo, (5, 8), logo)
    small.save(ASSETS / "wizard-small.bmp")


def main():
    ASSETS.mkdir(exist_ok=True)
    icon = render(S)
    icon.save(ASSETS / "icon.png")
    # ICO com varios tamanhos; os pequenos sao renderizados de novo para o neon nao sumir
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(256)] + [render(sz) if sz >= 64 else icon.resize((sz, sz), Image.LANCZOS) for sz in sizes[:-1]]
    frames[0].save(ASSETS / "icon.ico", sizes=[(sz, sz) for sz in sizes], append_images=frames[1:])
    wizard_images(icon)
    print("ok:", *(p.name for p in ASSETS.iterdir()))


if __name__ == "__main__":
    main()
