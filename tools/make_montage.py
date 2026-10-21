"""Reels-нарезка: много красивых клипов, смена каждые ~1.2 с, маленькая фраза с засечками на весь ролик.
python3 make_montage.py out.mp4 "Фраза" clip1.mp4 clip2.mp4 ... [--seg 1.2] [--dark 0.85] [--seed 1]
"""
import argparse, random, subprocess, os, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/truetype/google-fonts/Lora-Variable.ttf"

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).decode().strip())

def text_overlay(text, path, size=44, y_frac=0.42, sub=""):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name("Medium")
    except Exception:
        pass
    d = ImageDraw.Draw(im)
    # перенос, если фраза длинная
    lines = []
    for part in text.split("|"):  # "|" — принудительный перенос строки
        cur = ""
        for w in part.split():
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= W * 0.78: cur = t
            else: lines.append(cur); cur = w
        lines.append(cur)
    lh = int(size * 1.35)
    y0 = int(H * y_frac) - lh * len(lines) // 2
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sh)
    for i, ln in enumerate(lines):
        x = (W - d.textlength(ln, font=f)) / 2
        sd.text((x, y0 + i * lh + 2), ln, font=f, fill=(0, 0, 0, 200))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        x = (W - d.textlength(ln, font=f)) / 2
        d.text((x, y0 + i * lh), ln, font=f, fill=(255, 255, 255, 245))
    if sub:
        fs = ImageFont.truetype(FONT, int(size * 0.72))
        try: fs.set_variation_by_name("Regular")
        except Exception: pass
        ys = y0 + len(lines) * lh + int(size * 0.5)
        arrow = sub.endswith("↓")
        body = sub[:-1].rstrip() + " " if arrow else sub
        fa = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", int(size * 0.62))
        tw = d.textlength(body, font=fs) + (d.textlength("↓", font=fa) if arrow else 0)
        x = (W - tw) / 2
        sh2 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); s2 = ImageDraw.Draw(sh2)
        s2.text((x, ys + 2), body, font=fs, fill=(0, 0, 0, 200))
        if arrow: s2.text((x + d.textlength(body, font=fs), ys + 4), "↓", font=fa, fill=(0, 0, 0, 200))
        im.alpha_composite(sh2.filter(ImageFilter.GaussianBlur(4)))
        dd = ImageDraw.Draw(im)
        dd.text((x, ys), body, font=fs, fill=(255, 255, 255, 215))
        if arrow: dd.text((x + d.textlength(body, font=fs), ys + 2), "↓", font=fa, fill=(255, 255, 255, 215))
    im.save(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("text"); ap.add_argument("clips", nargs="+")
    ap.add_argument("--seg", type=float, default=1.2)
    ap.add_argument("--dark", type=float, default=0.85)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--size", type=int, default=44)
    ap.add_argument("--sub", default="Читай описание ↓")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    tmp = tempfile.mkdtemp()
    parts = []
    for i, c in enumerate(a.clips):
        d = dur(c)
        st = rnd.uniform(0.3, max(0.3, d - a.seg - 0.3))
        p = os.path.join(tmp, f"p{i:02d}.mp4")
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
              f"eq=brightness={-(1 - a.dark) * 0.35:.3f}:saturation=1.05:contrast=1.05,format=yuv420p")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{st:.2f}", "-i", c, "-t", f"{a.seg}",
                        "-an", "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "fast", p], check=True)
        parts.append(p)
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    ov = os.path.join(tmp, "text.png"); text_overlay(a.text, ov, a.size, sub=a.sub)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", ov,
                    "-filter_complex", "[0:v][1:v]overlay=0:0,format=yuv420p", "-c:v", "libx264", "-crf", "24",
                    "-preset", "slow", "-maxrate", "8M", "-bufsize", "16M", "-movflags", "+faststart", "-an", a.out],
                   check=True)

if __name__ == "__main__":
    main()
