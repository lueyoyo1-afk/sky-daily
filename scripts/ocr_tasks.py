#!/usr/bin/env python3.11
"""
OCR 每日任务模块（混合方案的「人工/OCR」部分）
- --make-sample : 生成一张仿超话白底黑字的「每日任务」测试图到 input/
- 默认          : 识别 input/ 下所有图片，用 tesseract(chi_sim) 提取任务文本，
                 再按 guides.json 的 keywords 匹配到具体任务名，写入 data.json
"""
import os, re, json, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = "/workspace"
INPUT_DIR = os.path.join(ROOT, "input")
DATA = os.path.join(ROOT, "data.json")
GUIDES = os.path.join(ROOT, "guides.json")
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


def make_sample():
    os.makedirs(INPUT_DIR, exist_ok=True)
    out = os.path.join(INPUT_DIR, "daily_tasks_sample.png")
    img = Image.new("RGB", (760, 540), "white")
    d = ImageDraw.Draw(img)
    try:
        title = ImageFont.truetype(FONT, 44, index=0)
        body = ImageFont.truetype(FONT, 36, index=0)
    except Exception:
        title = ImageFont.load_default(); body = ImageFont.load_default()
    d.rectangle([0, 0, 760, 12], fill=(124, 140, 255))
    d.text((30, 34), "光遇每日任务 · 10.09", fill=(20, 20, 40), font=title)
    tasks = [
        "1、与 4 位朋友击掌",
        "2、在云野重温先祖的美好回忆",
        "3、收集 30 点烛光",
        "4、在霞谷追逐散落的星光",
    ]
    y = 120
    for t in tasks:
        d.text((44, y), t, fill=(20, 20, 40), font=body)
        y += 76
    img.save(out)
    print("生成示例图:", out)


def ocr_image(path):
    im = Image.open(path).convert("L")
    w, h = im.size
    im = im.resize((w * 3, h * 3), Image.LANCZOS)
    im = im.point(lambda x: 0 if x < 150 else 255)   # 二值化提升中文识别率
    tmp = "/tmp/ocr_tmp.png"
    im.save(tmp)
    r = subprocess.run(["tesseract", tmp, "stdout", "-l", "chi_sim", "--psm", "6"],
                       capture_output=True, text=True)
    return r.stdout


def _match_line(line, g):
    kw = g.get("keywords", [])
    al = g.get("aliases", [])
    ok_kw = (not kw) or all(k in line for k in kw)        # 组合定位(AND)
    ok_al = (not al) or any(a in line for a in al)         # 同义词(OR)
    return ok_kw and ok_al

def match_guides(text, guides):
    found = []
    for line in text.splitlines():                          # 逐行匹配，防跨行误命中
        if not line.strip():
            continue
        for g in guides:
            if _match_line(line, g) and g["name"] not in found:
                found.append(g["name"])
    return found


def main():
    if "--make-sample" in sys.argv:
        make_sample()
        return
    guides = json.load(open(GUIDES, encoding="utf-8"))["guides"]
    files = [f for f in os.listdir(INPUT_DIR)
             if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
    if not files:
        print("input/ 无图片，先运行: python3.11 ocr_tasks.py --make-sample")
        return
    texts = [ocr_image(os.path.join(INPUT_DIR, f)) for f in files]
    full = "\n".join(texts)
    print("--- OCR 原始文本 ---\n" + full)
    tasks = match_guides(full, guides)
    data = json.load(open(DATA, encoding="utf-8"))
    data.setdefault("today", {})
    if tasks:
        data["today"]["dailyTasks"] = tasks
        data["today"]["dailyTasksSource"] = "ocr"
        print("识别到每日任务:", tasks)
    else:
        print("未识别到任务，保留原数据")
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已更新", DATA)


if __name__ == "__main__":
    main()
