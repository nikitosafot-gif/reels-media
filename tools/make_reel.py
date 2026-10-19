"""Генератор вертикальных reels: фон + цепляющий текст + мягкий эмбиент.
Использование: python3 make_reel.py <style> <out.mp4> "<строка1>|<строка2>|..." [--accent "слово1,слово2"] [--sub "подпись"]
Стили: dark, notes, bold
"""
import sys, math, subprocess, argparse, wave, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
F = "/usr/share/fonts/opentype/inter/"

def font(name, size):
    return ImageFont.truetype(F + name, size)

# ---------- фоны ----------
def bg_dark(t, rng):
    w, h = 216, 384
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    img[:] = (10, 10, 24)
    blobs = [((120, 60, 220), 0.0), ((30, 90, 200), 2.1), ((200, 50, 140), 4.2)]
    for col, ph in blobs:
        cx = w * (0.5 + 0.35 * math.sin(t * 0.35 + ph))
        cy = h * (0.5 + 0.30 * math.cos(t * 0.27 + ph * 1.3))
        d = ((x - cx) ** 2 + (y - cy) ** 2) / (w * 0.45) ** 2
        a = np.exp(-d)[..., None] * 0.55
        img = img * (1 - a) + np.array(col, np.float32) * a
    im = Image.fromarray(img.clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    return im

def bg_notes(t, rng, _cache={}):
    if "base" not in _cache:
        base = np.full((H, W, 3), (246, 241, 230), np.float32)
        noise = rng.normal(0, 6, (H, W, 1)).astype(np.float32)
        _cache["base"] = Image.fromarray((base + noise).clip(0, 255).astype(np.uint8))
    return _cache["base"].copy()

def bg_bold(t, rng):
    w, h = 108, 192
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    k = (x / w * math.cos(t * 0.25) + y / h * math.sin(t * 0.25 + 1.0)) * 0.5 + 0.5
    k = (k + 0.15 * np.sin(t * 0.8 + x / 18)).clip(0, 1)[..., None]
    c1 = np.array((255, 94, 58), np.float32)
    c2 = np.array((96, 52, 235), np.float32)
    img = c1 * (1 - k) + c2 * k
    return Image.fromarray(img.astype(np.uint8)).resize((W, H), Image.BICUBIC)

def bg_night(t, rng, _s={}):
    """Ночной город: размытые огни (боке), полосы фар, затемнение, виньетка, зерно."""
    w, h = 540, 960
    if "init" not in _s:
        r = np.random.default_rng(7)
        _s["bokeh"] = [(r.uniform(0, w), r.uniform(0, h), r.uniform(18, 70), r.uniform(-6, 6), r.uniform(-3, 3),
                        [(255, 180, 90), (255, 140, 60), (255, 220, 150), (120, 160, 255), (255, 90, 80)][r.integers(0, 5)],
                        r.uniform(0.25, 0.7), r.uniform(0, 6.28)) for _ in range(45)]
        _s["streaks"] = [(r.uniform(560, 900), r.uniform(0, 1), r.uniform(220, 520), r.choice([-1, 1]),
                          (255, 70, 50) if r.random() < .5 else (255, 230, 180)) for _ in range(14)]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        vig = 1 - 0.75 * (((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.65)) ** 2)
        _s["vig"] = vig.clip(0.15, 1)[..., None]
        _s["init"] = True
    im = Image.new("RGB", (w, h), (8, 8, 14))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for x, y, rad, vx, vy, col, a, ph in _s["bokeh"]:
        cx = (x + vx * t * 4) % (w + 140) - 70
        cy = (y + vy * t * 4) % (h + 140) - 70
        k = a * (0.75 + 0.25 * math.sin(t * 1.3 + ph))
        gd.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=tuple(int(c * k) for c in col))
    glow = glow.filter(ImageFilter.GaussianBlur(11))
    st = Image.new("RGB", (w, h), (0, 0, 0)); sd = ImageDraw.Draw(st)
    for y, off, sp, dirn, col in _s["streaks"]:
        L = 180
        x = ((off * (w + L) + dirn * sp * t) % (w + L)) - L
        for k in range(12):  # хвост, затухающий к краю
            f = (k + 1) / 12 if dirn > 0 else (12 - k) / 12
            seg = L / 12
            sd.ellipse((x + k * seg, y, x + (k + 1) * seg + 6, y + 6), fill=tuple(int(c * f ** 2) for c in col))
    st = st.filter(ImageFilter.GaussianBlur(5))
    arr = np.asarray(im, np.float32) + np.asarray(glow, np.float32) + np.asarray(st, np.float32) * 0.8
    big = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    a = np.asarray(big, np.float32) * _s["vig"] * 0.62  # затемнение под текст
    a += rng.normal(0, 5, (H // 2, W // 2, 1)).repeat(2, 0).repeat(2, 1)  # плёночное зерно
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))

class VideoBG:
    """Фон из видеоклипа: вертикальный кроп, замедление, затемнение, виньетка, зерно."""
    def __init__(self, path, speed=0.8, dark=0.55):
        self.dark = dark
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"setpts=PTS/{speed},fps={FPS},eq=saturation=0.85:contrast=1.08")
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-i", path,
                                   "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        vig = 1 - 0.6 * (((xx - W / 2) / (W * 0.8)) ** 2 + ((yy - H / 2) / (H * 0.7)) ** 2)
        self.vig = vig.clip(0.25, 1)[..., None]
    def __call__(self, t, rng):
        raw = self.p.stdout.read(W * H * 3)
        img = Image.frombuffer("RGB", (W, H), raw)
        z = 1.0 + 0.07 * min(1.0, t / 8.0)  # плавный зум до +7%
        cw, ch = W / z, H / z
        img = img.resize((W, H), Image.BICUBIC, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2))
        a = np.asarray(img, np.float32)
        a = a * self.vig * self.dark
        a += rng.normal(0, 5, (H // 2, W // 2, 1)).repeat(2, 0).repeat(2, 1)
        return Image.fromarray(a.clip(0, 255).astype(np.uint8))

# ---------- текст ----------
def ease(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3

def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if draw.textlength(test, font=fnt) <= maxw:
            cur = test
        else:
            lines.append(cur); cur = wd
    if cur: lines.append(cur)
    return lines

def draw_words(draw, x, y, line, fnt, base_col, acc_col, accents):
    for wd in line.split(" "):
        clean = wd.strip(".,!?:;—«»").lower()
        col = acc_col if clean in accents else base_col
        draw.text((x, y), wd, font=fnt, fill=col)
        x += draw.textlength(wd + " ", font=fnt)

def render(style, out, blocks, accents, sub, dur=8.0, seed=1, audio=True, bgvideo=None, speed=0.8, dark=0.55):
    rng = np.random.default_rng(seed)
    n = int(dur * FPS)
    tmpd = Image.new("RGB", (10, 10)); dd = ImageDraw.Draw(tmpd)

    if style in ("dark", "night"):
        fnt = font("InterDisplay-ExtraBold.otf", 66); base, acc = (255, 255, 255), (255, 200, 70)
        bgf = bg_dark if style == "dark" else bg_night; maxw = 820; lh = 80
    elif style == "notes":
        fnt = font("Inter-Bold.otf", 76); base, acc = (28, 28, 30), (230, 70, 40)
        bgf = bg_notes; maxw = 880; lh = 98
    else:
        fnt = font("InterDisplay-ExtraBold.otf", 86); base, acc = (20, 20, 24), (110, 40, 230)
        bgf = bg_bold; maxw = 820; lh = 128

    if bgvideo:
        bgf = VideoBG(bgvideo, speed, dark)
    # раскладка строк по блокам
    layout = []
    for bi, b in enumerate(blocks):
        for ln in wrap(dd, b, fnt, maxw):
            layout.append((bi, ln))
    total_h = len(layout) * lh + (len(blocks) - 1) * 26
    top = (H - total_h) // 2 - 80  # чуть выше центра — вне зоны подписи Instagram
    subf = font("Inter-SemiBold.otf", 36)

    # какой текст показан к какому времени
    if style == "notes":
        full = "\n".join(l for _, l in layout)
        typing_end = dur * 0.55
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "25", "-maxrate", "8M", "-bufsize", "16M", out + ".v.mp4"],
                          stdin=subprocess.PIPE)
    for i in range(n):
        t = i / FPS
        im = bgf(t, rng).convert("RGBA")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        if style == "notes":
            # шапка заметки
            d.text((90, 300), "Заметки", font=font("Inter-SemiBold.otf", 40), fill=(200, 150, 30))
            d.line((90, 370, W - 90, 370), fill=(215, 205, 190), width=3)
            chars = int(len(full) * min(1, t / typing_end))
            shown = full[:chars]
            y = 430
            for ln_i, ln in enumerate(shown.split("\n")):
                draw_words(d, 90, y, ln, fnt, base, acc, accents)
                y += lh
            if t < typing_end + 0.5 and int(t * 2) % 2 == 0:
                lastw = d.textlength(shown.split("\n")[-1], font=fnt)
                d.rectangle((92 + lastw, y - lh + 8, 98 + lastw, y - lh + 84), fill=(200, 150, 30))
        else:
            y = top; prev_b = 0
            for li, (bi, ln) in enumerate(layout):
                if bi != prev_b: y += 26; prev_b = bi
                start = -1.0 if bi == 0 else (0.35 + (bi - 1) * 0.5 + li * 0.08)
                p = ease((t - start) / 0.45)
                if p > 0:
                    lw = d.textlength(ln, font=fnt)
                    x = (W - lw) / 2
                    dy = (1 - p) * 40
                    if style == "bold":
                        pad = 22
                        box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                        ImageDraw.Draw(box).rounded_rectangle(
                            (x - pad, y + dy - 6, x + lw + pad, y + dy + lh - 22), 22,
                            fill=(255, 255, 255, int(255 * p)))
                        layer.alpha_composite(box)
                        d = ImageDraw.Draw(layer)
                    else:
                        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                        ImageDraw.Draw(sh).text((x + 4, y + dy + 4), ln, font=fnt, fill=(0, 0, 0, int(170 * p)))
                        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
                        d = ImageDraw.Draw(layer)
                    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    draw_words(ImageDraw.Draw(tmp), x, y + dy, ln, fnt, base + (255,), acc + (255,), accents)
                    if p < 1:
                        a = tmp.split()[3].point(lambda v: int(v * p)); tmp.putalpha(a)
                    layer.alpha_composite(tmp)
                    d = ImageDraw.Draw(layer)
                y += lh

        # подпись внизу («читай описание»)
        if sub:
            st = (dur * 0.6) if style == "notes" else (0.35 + (len(blocks) - 1) * 0.5 + 0.2)
            p = ease((t - st) / 0.5)
            if p > 0:
                bob = math.sin(t * 5) * 8
                sw = d.textlength(sub, font=subf)
                col = (40, 40, 40) if style == "notes" else (255, 255, 255)
                tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                td = ImageDraw.Draw(tmp)
                if style != "notes":
                    td.rounded_rectangle(((W - sw) / 2 - 28, 1200 + bob, (W + sw) / 2 + 28, 1266 + bob), 33,
                                         fill=(0, 0, 0, 120))
                td.text(((W - sw) / 2, 1211 + bob), sub, font=subf, fill=col + (255,))
                tmp.putalpha(tmp.split()[3].point(lambda v: int(v * p)))
                layer.alpha_composite(tmp)

        im.alpha_composite(layer)
        ff.stdin.write(im.convert("RGB").tobytes())
    ff.stdin.close(); ff.wait()
    if bgvideo: bgf.p.kill()
    if not audio:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out + ".v.mp4", "-c", "copy",
                        "-movflags", "+faststart", out], check=True)
        os.remove(out + ".v.mp4"); return

    # мягкий эмбиент-пэд (свой, без авторских прав)
    sr = 44100; tt = np.arange(int(sr * dur)) / sr
    chords = [[220.0, 277.18, 329.63], [196.0, 246.94, 293.66], [174.61, 220.0, 261.63], [196.0, 246.94, 311.13]]
    audio = np.zeros_like(tt)
    seg = dur / len(chords)
    for ci, ch in enumerate(chords):
        env = np.clip(1 - np.abs((tt - (ci + 0.5) * seg) / (seg * 0.75)), 0, 1) ** 1.5
        for f0 in ch:
            audio += env * (np.sin(2 * np.pi * f0 * tt) + 0.3 * np.sin(2 * np.pi * f0 * 2.003 * tt))
    audio *= np.minimum(1, tt / 0.8) * np.minimum(1, (dur - tt) / 0.8)
    audio = (audio / np.abs(audio).max() * 0.22 * 32767).astype(np.int16)
    with wave.open(out + ".a.wav", "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(audio.tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out + ".v.mp4", "-i", out + ".a.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out], check=True)
    os.remove(out + ".v.mp4"); os.remove(out + ".a.wav")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("style"); ap.add_argument("out"); ap.add_argument("text")
    ap.add_argument("--accent", default=""); ap.add_argument("--sub", default="")
    ap.add_argument("--dur", type=float, default=8.0)
    ap.add_argument("--noaudio", action="store_true")
    ap.add_argument("--bgvideo"); ap.add_argument("--speed", type=float, default=0.8)
    ap.add_argument("--dark", type=float, default=0.55)
    a = ap.parse_args()
    render(a.style, a.out, a.text.split("|"), {w.strip().lower() for w in a.accent.split(",") if w.strip()}, a.sub, a.dur, audio=not a.noaudio, bgvideo=a.bgvideo, speed=a.speed, dark=a.dark)
