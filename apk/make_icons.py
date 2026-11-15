"""按 web/public/icon.svg 的几何画安卓图标和启动图，直接写进 android/app/src/main/res。
用法：python make_icons.py        （需要 Pillow）
"""
from pathlib import Path
from PIL import Image, ImageDraw

RES = Path(__file__).resolve().parent / "android" / "app" / "src" / "main" / "res"
INK, PAPER, BLUE, LIME = (21, 23, 26), (236, 238, 232), (39, 64, 232), (212, 242, 74)
SS = 4   # 超采样倍数，缩小后边缘才平滑

# icon.svg 里的四块砖（512 画布）：x, y, w, h, 颜色
BRICKS = [(96, 112, 200, 124, BLUE + (255,)), (316, 112, 100, 124, PAPER + (72,)),
          (96, 256, 100, 124, PAPER + (72,)), (216, 256, 200, 124, LIME + (255,))]
BRICKS_ON_LIGHT = [(x, y, w, h, c if c[:3] != PAPER else INK + (46,)) for x, y, w, h, c in BRICKS]


def bricks(size: int, box: float, bricks_def=BRICKS, offset=(0.0, 0.0)) -> Image.Image:
    """透明底的一组砖。box = 砖群（原 320x268 的外框）占画布宽度的比例。"""
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = size * SS * box / 320            # 原图里砖群宽 320
    ox = size * SS * (0.5 + offset[0]) - 160 * k   # 砖群水平居中（原 x 从 96 到 416，中心 256）
    oy = size * SS * (0.5 + offset[1]) - 134 * k   # 垂直居中（原 y 从 112 到 380，中心 246，取 134 对齐砖群高 268 的一半）
    for x, y, w, h, c in bricks_def:
        x0, y0 = ox + (x - 96) * k, oy + (y - 112) * k
        d.rounded_rectangle([x0, y0, x0 + w * k, y0 + h * k], radius=26 * k, fill=c)
    return img


def finish(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def legacy(size: int, round_: bool) -> Image.Image:
    bg = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    full = [0, 0, size * SS - 1, size * SS - 1]
    d.ellipse(full, fill=INK + (255,)) if round_ else d.rounded_rectangle(full, radius=size * SS * 0.22, fill=INK + (255,))
    bg.alpha_composite(bricks(size, 0.58 if round_ else 0.62))
    return finish(bg, size)


def foreground(size: int) -> Image.Image:
    return finish(bricks(size, 0.5), size)    # 自适应图标安全区是中间 61%，砖群占 50%


def splash(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), PAPER + (255,))
    side = int(min(w, h) * 0.34)
    logo = finish(bricks(side, 0.62, BRICKS_ON_LIGHT), side)
    img.alpha_composite(logo, ((w - side) // 2, (h - side) // 2))
    return img


LEGACY = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
ADAPTIVE = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}

if __name__ == "__main__":
    for dens, s in LEGACY.items():
        legacy(s, False).save(RES / f"mipmap-{dens}" / "ic_launcher.png")
        legacy(s, True).save(RES / f"mipmap-{dens}" / "ic_launcher_round.png")
    for dens, s in ADAPTIVE.items():
        foreground(s).save(RES / f"mipmap-{dens}" / "ic_launcher_foreground.png")
    n = 0
    for f in RES.glob("drawable*/splash.png"):
        w, h = Image.open(f).size
        splash(w, h).convert("RGB").save(f)
        n += 1
    (RES / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#15171A</color>\n</resources>\n', encoding="utf-8")
    print(f"图标 {len(LEGACY) * 2 + len(ADAPTIVE)} 张，启动图 {n} 张")
