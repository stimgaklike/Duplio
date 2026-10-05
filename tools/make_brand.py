"""Из исходников логотипа (branding/src) сделать всё, что нужно программе, установщику и README.

python tools/make_brand.py

branding/src — картинки из генератора (прозрачный фон, 1254×1254):
  mark-color.png      цветной знак без надписи
  app-icon-plate.png  знак на белой плашке — значок программы
  mark-mono.png       одноцветный тёмный знак — значок в трее
  logo-with-text.png  знак с надписью Duplio — для README
"""

import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "branding", "src")
OUT = os.path.join(ROOT, "branding")
ICONS = os.path.join(ROOT, "icons")


def load(name):
    """Открыть исходник и починить альфу: генератор сохранил «непрозрачное» как 253–254."""
    a = np.array(Image.open(os.path.join(SRC, name)).convert("RGBA"))
    al = a[..., 3]
    al[al >= 250] = 255
    return Image.fromarray(a)


def crop(img, pad=0.06):
    """Обрезать по рисунку и уложить в квадрат с полями pad от стороны."""
    a = np.array(img)[..., 3]
    ys, xs = np.where(a > 20)
    box = img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    side = int(max(box.size) * (1 + 2 * pad))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(box, ((side - box.width) // 2, (side - box.height) // 2))
    return sq


def crop_tight(img, pad=0.03):
    a = np.array(img)[..., 3]
    ys, xs = np.where(a > 20)
    box = img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    p = int(max(box.size) * pad)
    out = Image.new("RGBA", (box.width + 2 * p, box.height + 2 * p), (0, 0, 0, 0))
    out.alpha_composite(box, (p, p))
    return out


def recolor(img, rgb, only_dark=False):
    """Перекрасить рисунок в один цвет, сохранив альфу (only_dark — только тёмные пиксели: надпись)."""
    a = np.array(img).astype(np.int32)
    if only_dark:
        mask = (a[..., :3].max(axis=2) < 90) & (a[..., 3] > 0)
    else:
        mask = a[..., 3] > 0
    for i, c in enumerate(rgb):
        a[..., i][mask] = c
    return Image.fromarray(a.astype(np.uint8))


def sized(img, s):
    return img.resize((s, s), Image.LANCZOS)


def flat(img, size, bg=(255, 255, 255)):
    """Картинка на белом в BMP-совместимом виде (для установщика)."""
    w, h = size
    canvas = Image.new("RGB", (w, h), bg)
    pic = img.copy()
    pic.thumbnail((w, h), Image.LANCZOS)
    tile = Image.new("RGBA", (w, h), bg + (255,))
    tile.alpha_composite(pic, ((w - pic.width) // 2, (h - pic.height) // 2))
    canvas.paste(tile.convert("RGB"))
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    mark = crop(load("mark-color.png"))
    plate = crop(load("app-icon-plate.png"), pad=0.02)
    mono = crop(load("mark-mono.png"))
    logo = crop_tight(load("logo-with-text.png"))

    # Значок программы (exe, окно, ярлыки, установщик): с 48 px — на плашке, как задумано;
    # на 16–32 px плашка съедает место и знак превращается в точку — там знак без неё.
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [sized(mark if s <= 32 else plate, s) for s in sizes]
    frames[-1].save(os.path.join(ROOT, "icon.ico"), sizes=[(s, s) for s in sizes], append_images=frames[:-1])

    # Значок в трее: одноцветный. Белый — для тёмной панели задач, тёмный — для светлой.
    tray_sizes = [16, 20, 24, 32, 40, 48, 64]
    for name, img in (("tray-dark-taskbar", recolor(mono, (255, 255, 255))),
                      ("tray-light-taskbar", recolor(mono, (27, 27, 35)))):
        fr = [sized(img, s) for s in tray_sizes]
        fr[-1].save(os.path.join(ICONS, name + ".ico"), sizes=[(s, s) for s in tray_sizes], append_images=fr[:-1])

    # Знак рядом с вкладками в окне.
    sized(mark, 64).save(os.path.join(ICONS, "mark-64.png"))

    # README: логотип с надписью для светлой темы GitHub и он же с белой надписью — для тёмной.
    w = 560
    h = round(logo.height * w / logo.width)
    logo.resize((w, h), Image.LANCZOS).save(os.path.join(OUT, "logo-light.png"))
    recolor(logo, (240, 242, 245), only_dark=True).resize((w, h), Image.LANCZOS).save(
        os.path.join(OUT, "logo-dark.png"))
    sized(mark, 512).save(os.path.join(OUT, "mark-512.png"))

    # Установщик: маленькая картинка вверху страниц (55×55 и вдвое крупнее для экранов с масштабом)
    # и большая слева на первой и последней странице (164×314 и вдвое крупнее).
    for scale in (1, 2):
        flat(plate, (55 * scale, 55 * scale)).save(os.path.join(OUT, f"wizard-small-{scale}x.bmp"))
        big = Image.new("RGB", (164 * scale, 314 * scale), (255, 255, 255))
        lg = logo.copy()
        lg.thumbnail((int(132 * scale), int(200 * scale)), Image.LANCZOS)
        tile = Image.new("RGBA", big.size, (255, 255, 255, 255))
        tile.alpha_composite(lg, ((big.width - lg.width) // 2, (big.height - lg.height) // 2))
        tile.convert("RGB").save(os.path.join(OUT, f"wizard-large-{scale}x.bmp"))
    print("готово:", sorted(os.listdir(OUT)), sorted(f for f in os.listdir(ICONS) if "tray" in f or "mark" in f))


if __name__ == "__main__":
    main()
