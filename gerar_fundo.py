"""Gera um fundo de setup gamer (imagem e video em loop) direto na pasta "fundos".

A cena e pintada em camadas: a parte "apagada" (parede, madeira, moveis) e uma
camada por grupo de luzes (hexagonos, neon, fitas LED). O brilho (bloom) de cada
luz e pre-calculado; no video so muda a intensidade de cada grupo por quadro, por
isso a animacao fica leve e o loop fecha perfeito.

Uso:
  python gerar_fundo.py                         (tema roxo, texto "GAME ON")
  python gerar_fundo.py --tema vermelho --texto "GG"
  python gerar_fundo.py --sem-video
Temas: roxo, vermelho, verde, azul
"""

import argparse
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
SS = 2  # supersampling para bordas suaves
OUT_DIR = Path(__file__).resolve().parent / "fundos"
FONTS = Path("C:/Windows/Fonts")

THEMES = {
    "roxo": [(1.0, 0.12, 0.75), (0.55, 0.25, 1.0), (0.1, 0.75, 1.0)],
    "vermelho": [(1.0, 0.1, 0.15), (1.0, 0.45, 0.05), (1.0, 0.15, 0.55)],
    "verde": [(0.1, 1.0, 0.45), (0.05, 0.8, 0.8), (0.6, 1.0, 0.1)],
    "azul": [(0.1, 0.45, 1.0), (0.1, 0.85, 1.0), (0.6, 0.7, 1.0)],
}


def mask(draw_fn):
    """Desenha em 2x com PIL e reduz: mascara float 0..1 com antialiasing.

    So a area desenhada e reduzida (bbox), o que deixa a montagem da cena ~10x mais rapida.
    """
    img = Image.new("L", (W * SS, H * SS), 0)
    draw_fn(ImageDraw.Draw(img), SS)
    out = np.zeros((H, W), np.float32)
    box = img.getbbox()
    if box is None:
        return out
    x0, y0 = box[0] // SS, box[1] // SS
    x1, y1 = min(W, -(-box[2] // SS)), min(H, -(-box[3] // SS))
    crop = img.crop((x0 * SS, y0 * SS, x1 * SS, y1 * SS)).resize((x1 - x0, y1 - y0), Image.LANCZOS)
    out[y0:y1, x0:x1] = np.asarray(crop, np.float32) / 255
    return out


def paint(img, m, color):
    img *= 1 - m[..., None]
    img += m[..., None] * np.float32(color)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def theme_color(cols, t):
    """Gradiente continuo passando pelas 3 cores do tema (t de 0 a 1)."""
    t = min(max(t, 0), 1) * (len(cols) - 1)
    i = min(int(t), len(cols) - 2)
    return mix(cols[i], cols[i + 1], t - i)


def bloom(emissive):
    """Brilho em varias escalas, como uma camera vendo uma luz forte."""
    out = emissive + cv2.GaussianBlur(emissive, (0, 0), 4) * 0.6
    # brilhos largos em resolucao reduzida: mesmo resultado, muito mais rapido
    for sigma, gain, k in ((18, 0.5, 2), (60, 0.45, 4), (160, 0.35, 8)):
        small = cv2.resize(emissive, (W // k, H // k), interpolation=cv2.INTER_AREA)
        out += cv2.resize(cv2.GaussianBlur(small, (0, 0), sigma / k), (W, H), interpolation=cv2.INTER_LINEAR) * gain
    return out


def hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(60 * k + 30)), cy + r * math.sin(math.radians(60 * k + 30)))
            for k in range(6)]


class Scene:
    def __init__(self, theme, text):
        self.c = THEMES[theme]
        self.text = text
        self.base = np.zeros((H, W, 3), np.float32)
        self.lights = []  # (nome, glow pre-calculado, fase da animacao)

    def light(self, name, m, color, strength=1.0, phase=0.0):
        """Registra uma luz: o tubo/painel em si e o brilho que ele espalha."""
        emissive = m[..., None] * np.float32(color) * strength
        self.lights.append((name, bloom(emissive), phase))

    # ---------- cena ----------
    def build(self):
        self.wall()
        self.slat_wall()
        self.hex_panels()
        self.neon_sign()
        self.shelves()
        self.desk()
        self.ceiling_cove()
        return self

    def wall(self):
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
        top, bottom = np.float32((0.075, 0.065, 0.10)), np.float32((0.035, 0.03, 0.05))
        self.base[:] = top * (1 - y[..., None]) + bottom * y[..., None]
        # textura sutil de reboco
        rng = np.random.default_rng(7)
        noise = cv2.GaussianBlur(rng.standard_normal((H, W)).astype(np.float32), (0, 0), 1.2)
        self.base *= (1 + noise[..., None] * 0.04)
        # leve luz ambiente colorida nas laterais
        self.base += (np.exp(-((x - 0.1) ** 2) / 0.05) * 0.03)[..., None] * np.float32(self.c[0])
        self.base += (np.exp(-((x - 0.92) ** 2) / 0.04) * 0.03)[..., None] * np.float32(self.c[2])

    def slat_wall(self):
        """Painel ripado de madeira na direita (tendencia de setup)."""
        x0, x1, y0, y1 = 1420, 1920, 70, 900
        felt = mask(lambda d, s: d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], fill=255))
        paint(self.base, felt, (0.018, 0.016, 0.02))
        rng = np.random.default_rng(3)
        slat_w, gap = 26, 12
        x = x0 + 8
        while x + slat_w <= x1:
            tone = 0.8 + rng.random() * 0.35
            wood = (0.20 * tone, 0.13 * tone, 0.085 * tone)
            m = mask(lambda d, s, x=x: d.rectangle([x * s, (y0 + 6) * s, (x + slat_w) * s, (y1 - 6) * s], fill=255))
            paint(self.base, m, wood)
            # brilho lateral da ripa (luz vindo de cima/esquerda)
            hl = mask(lambda d, s, x=x: d.rectangle([x * s, (y0 + 6) * s, (x + 3) * s, (y1 - 6) * s], fill=255))
            self.base += hl[..., None] * np.float32(wood) * 0.6
            x += slat_w + gap
        # veios: ruido esticado na vertical
        grain = cv2.resize(rng.standard_normal((40, W // 6)).astype(np.float32), (W, H))
        region = np.zeros((H, W), np.float32)
        region[y0:y1, x0:x1] = 1
        self.base *= 1 + (grain * region * 0.08)[..., None]
        # fita LED escondida atras do painel (contorno)
        edge = mask(lambda d, s: d.rectangle([(x0 - 6) * s, (y0 - 6) * s, (x0 - 2) * s, (y1 + 6) * s], fill=255))
        self.light("ripado", edge, self.c[2], 1.6, phase=0.5)

    def hex_panels(self):
        """Paineis hexagonais de LED (estilo Nanoleaf) no alto, a esquerda."""
        r = 62
        dx, dy = r * math.sqrt(3), r * 1.5
        cells = [(0, 0), (1, 0), (2, 0), (0.5, 1), (1.5, 1), (2.5, 1), (1, 2), (3, 2), (2, -1)]
        ox, oy = 150, 230
        for i, (cx, cy) in enumerate(cells):
            px, py = ox + cx * dx, oy + cy * dy
            frame = mask(lambda d, s, px=px, py=py: d.polygon([(a * s, b * s) for a, b in hexagon(px, py, r - 3)], fill=255))
            paint(self.base, frame, (0.06, 0.06, 0.07))
            core = mask(lambda d, s, px=px, py=py: d.polygon([(a * s, b * s) for a, b in hexagon(px, py, r - 9)], fill=255))
            # painel mais claro no centro, como difusor de LED
            yy, xx = np.ogrid[:H, :W]
            falloff = np.clip(1.15 - np.sqrt((xx - px) ** 2 + (yy - py) ** 2) / (r * 1.1), 0.55, 1).astype(np.float32)
            color = theme_color(self.c, (cx + cy * 0.5) / 3.5)
            self.light(f"hex{i}", core * falloff, color, 0.62, phase=i / len(cells))

    def neon_sign(self):
        size = 130
        font = ImageFont.truetype(str(FONTS / "segoescb.ttf"), size * SS)
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        box = probe.textbbox((0, 0), self.text, font=font)
        tw = (box[2] - box[0]) / SS
        if tw > 760:  # texto longo: reduz para caber entre os hexagonos e o ripado
            size = int(size * 760 / tw)
            font = ImageFont.truetype(str(FONTS / "segoescb.ttf"), size * SS)
            box = probe.textbbox((0, 0), self.text, font=font)
            tw = (box[2] - box[0]) / SS
        cx, cy = 975, 170

        def draw(d, s, width):
            d.text(((cx - tw / 2) * s, (cy - size * 0.75) * s), self.text, font=font, fill=0,
                   stroke_width=int(width * s), stroke_fill=255)

        # placa de acrilico atras do neon
        plate = mask(lambda d, s: d.rounded_rectangle([(cx - tw / 2 - 45) * s, (cy - 95) * s,
                                                       (cx + tw / 2 + 45) * s, (cy + 105) * s], 26 * s, fill=255))
        paint(self.base, plate * 0.3, (0.12, 0.12, 0.16))
        tube = mask(lambda d, s: draw(d, s, 5))
        core = mask(lambda d, s: draw(d, s, 1.5))
        self.light("neon", tube, self.c[0], 1.0, phase=0.0)
        self.light("neon_core", core, mix(self.c[0], (1, 1, 1), 0.6), 0.35, phase=0.0)

    def shelves(self):
        cols = self.c
        for (x0, x1, y), side in (((90, 560, 640), 0), ((1480, 1860, 470), 1)):
            board = mask(lambda d, s: d.rounded_rectangle([x0 * s, y * s, x1 * s, (y + 22) * s], 4 * s, fill=255))
            paint(self.base, board, (0.17, 0.11, 0.07))
            top = mask(lambda d, s: d.rectangle([x0 * s, y * s, x1 * s, (y + 3) * s], fill=255))
            self.base += top[..., None] * np.float32((0.12, 0.08, 0.05))
            strip = mask(lambda d, s: d.rectangle([(x0 + 10) * s, (y + 22) * s, (x1 - 10) * s, (y + 26) * s], fill=255))
            self.light(f"prateleira{side}", strip, cols[1], 1.3, phase=0.25 + side * 0.5)
            self.shelf_items(x0, x1, y, side)

    def shelf_items(self, x0, x1, y, side):
        rng = np.random.default_rng(10 + side)
        x = x0 + 25
        # caixas de jogos / livros em pe
        for _ in range(7):
            w, h = rng.integers(16, 26), rng.integers(110, 150)
            tone = rng.choice([0.25, 0.4, 0.55])
            col = mix((0.05, 0.05, 0.07), theme_color(self.c, rng.random()), tone * 0.5)
            m = mask(lambda d, s, x=x, w=w, h=h: d.rectangle([x * s, (y - h) * s, (x + w) * s, y * s], fill=255))
            paint(self.base, m, col)
            x += w + 3
        x += 30
        # vaso com planta
        pot = mask(lambda d, s, x=x: d.polygon([((x) * s, (y - 60) * s), ((x + 70) * s, (y - 60) * s),
                                                ((x + 60) * s, y * s), ((x + 10) * s, y * s)], fill=255))
        paint(self.base, pot, (0.75, 0.74, 0.72))
        for k in range(14):
            ang = math.radians(-160 + k * 10 + rng.normal(0, 4))
            ln = rng.integers(70, 120)
            ex, ey = x + 35 + math.cos(ang) * ln, y - 60 + math.sin(ang) * ln
            m = mask(lambda d, s, ex=ex, ey=ey, x=x: d.line([((x + 35) * s, (y - 60) * s), (ex * s, ey * s)],
                                                            fill=255, width=int(9 * s)))
            paint(self.base, m, (0.05 + rng.random() * 0.04, 0.22 + rng.random() * 0.1, 0.09))
        x += 110
        if x + 120 < x1:
            # cubo de luz
            cube = mask(lambda d, s, x=x: d.rounded_rectangle([x * s, (y - 70) * s, (x + 70) * s, y * s], 8 * s, fill=255))
            self.light(f"cubo{side}", cube, self.c[2 - side * 2], 0.55, phase=0.6 + side * 0.2)

    def desk(self):
        top_y = 965
        top = mask(lambda d, s: d.polygon([(0, top_y * s), (W * s, top_y * s), (W * s, H * s), (0, H * s)], fill=255))
        paint(self.base, top, (0.03, 0.028, 0.035))
        mat = mask(lambda d, s: d.rounded_rectangle([140 * s, (top_y + 18) * s, 1780 * s, (H + 40) * s], 18 * s, fill=255))
        paint(self.base, mat, (0.018, 0.018, 0.024))
        # borda RGB do mousepad em segmentos (anima como luz correndo)
        segs = 12
        for k in range(segs):
            a, b = 140 + (1640 / segs) * k, 140 + (1640 / segs) * (k + 1)
            m = mask(lambda d, s, a=a, b=b: d.rectangle([a * s, (top_y + 15) * s, b * s, (top_y + 21) * s], fill=255))
            self.light(f"mesa{k}", m, theme_color(self.c, k / (segs - 1)), 1.2, phase=k / segs)
        # caixas de som nas pontas
        for sx in (40, 1770):
            body = mask(lambda d, s, sx=sx: d.rounded_rectangle([sx * s, 760 * s, (sx + 110) * s, top_y * s], 10 * s, fill=255))
            paint(self.base, body, (0.045, 0.045, 0.055))
            woofer = mask(lambda d, s, sx=sx: d.ellipse([(sx + 15) * s, 860 * s, (sx + 95) * s, 940 * s], fill=255))
            paint(self.base, woofer, (0.015, 0.015, 0.02))
            tweeter = mask(lambda d, s, sx=sx: d.ellipse([(sx + 37) * s, 790 * s, (sx + 73) * s, 826 * s], fill=255))
            paint(self.base, tweeter, (0.02, 0.02, 0.025))
            ring = mask(lambda d, s, sx=sx: d.ellipse([(sx + 13) * s, 858 * s, (sx + 97) * s, 942 * s],
                                                      outline=255, width=int(2 * s)))
            self.light(f"som{sx}", ring, self.c[0] if sx < 900 else self.c[2], 1.0, phase=0.4)

    def ceiling_cove(self):
        """Fita LED no teto lavando a parede de cima para baixo."""
        strip = mask(lambda d, s: d.rectangle([0, 0, W * s, 5 * s], fill=255))
        self.light("teto", strip, self.c[1], 1.5, phase=0.0)
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        self.base += np.exp(-y / 0.18) * np.float32(self.c[1]) * 0.12

    # ---------- render ----------
    def render(self, t=None):
        """t em [0,1) para animar; None = todas as luzes no brilho base."""
        img = self.base.copy()
        for name, glow, phase in self.lights:
            if t is None:
                w = 1.0
            elif name.startswith("hex") or name.startswith("mesa"):
                w = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * (t * 2 - phase)))  # onda correndo
            elif name.startswith("neon"):
                w = 0.93 + 0.07 * math.sin(2 * math.pi * t * 4)  # respiracao bem sutil
            else:
                w = 0.85 + 0.15 * math.sin(2 * math.pi * (t + phase))
            img += glow * w
        return finish(img)


def finish(img):
    # tone mapping pelo canal mais forte: a luz fica intensa sem desbotar para o branco
    peak = img.max(axis=2, keepdims=True)
    img = img * ((1 - np.exp(-peak * 2.1)) / np.maximum(peak, 1e-6))
    yy, xx = np.ogrid[:H, :W]
    vig = 1 - 0.35 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.4
    img *= np.clip(vig, 0, 1)[..., None]
    img = np.clip(img, 0, 1) ** (1 / 1.1)
    return (img * 255 + np.random.default_rng().normal(0, 1.2, img.shape)).clip(0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description="Gera fundo de setup gamer")
    ap.add_argument("--tema", choices=THEMES, default="roxo")
    ap.add_argument("--texto", default="GAME ON")
    ap.add_argument("--sem-video", action="store_true")
    ap.add_argument("--segundos", type=int, default=8)
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    name = f"setup-{args.tema}"
    print("Montando a cena...")
    scene = Scene(args.tema, args.texto).build()
    still = scene.render()
    Image.fromarray(still).save(OUT_DIR / f"{name}.jpg", quality=95)
    print(f"Imagem: {OUT_DIR / (name + '.jpg')}")

    if not args.sem_video:
        fps, vw, vh = 30, 1280, 720
        path = OUT_DIR / f"{name}-animado.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (vw, vh))
        total = fps * args.segundos
        for i in range(total):
            frame = scene.render(i / total)
            writer.write(cv2.cvtColor(cv2.resize(frame, (vw, vh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR))
            if i % 30 == 0:
                print(f"  video {i * 100 // total}%")
        writer.release()
        print(f"Video: {path}")


if __name__ == "__main__":
    main()
