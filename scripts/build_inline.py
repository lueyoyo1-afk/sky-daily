#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_inline.py —— 把 data.json / guides.json / seasonGuides.json / events.json
全量内联进 index.html，使页面在 file:// 直接双击打开时也能显示完整数据
（浏览器会拦截 file:// 下的 fetch，所以必须内联）。

用法：
    python3 build_inline.py
每次更新任一 json 后运行一次即可。
"""
import json, re, os, sys, io, base64

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /workspace
HTML = os.path.join(BASE, "index.html")

# 形如 assets/xxx.jpg 的本地资源引用（会被内联为 base64，避免脱离 assets/ 目录后裂图）
IMG_RE = re.compile(r"^assets/[A-Za-z0-9_.\-/]+\.(?:jpe?g|png|webp|gif)$", re.I)
IMG_MAX_EDGE = 1100   # 内联前限制最长边，兼顾清晰度与体积
IMG_QUALITY  = 82

def _compress(path):
    """把本地图片压成更小的字节，返回 (mime, bytes)。失败则回退原图。"""
    try:
        from PIL import Image
        im = Image.open(path)
        fmt = (im.format or "JPEG").upper()
        w, h = im.size
        if max(w, h) > IMG_MAX_EDGE:
            s = IMG_MAX_EDGE / max(w, h)
            im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
        buf = io.BytesIO()
        low = path.lower()
        if fmt in ("JPEG", "JPG") or low.endswith((".jpg", ".jpeg")):
            im.convert("RGB").save(buf, "JPEG", quality=IMG_QUALITY, optimize=True, progressive=True)
            return "image/jpeg", buf.getvalue()
        if fmt == "PNG":
            im.save(buf, "PNG", optimize=True)
            return "image/png", buf.getvalue()
        im.save(buf, fmt if fmt in ("WEBP", "GIF") else "PNG")
        return "image/" + fmt.lower(), buf.getvalue()
    except Exception as e:
        print(f"    ! 压缩失败，内联原图：{e}")
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}.get(
                    os.path.splitext(path)[1].lower(), "application/octet-stream")
        with open(path, "rb") as f:
            return mime, f.read()

def asset_uri(rel):
    p = os.path.join(BASE, rel)
    if not os.path.exists(p):
        print(f"    ! 找不到 {rel}，跳过内联")
        return None
    mime, b = _compress(p)
    print(f"    · 内联 {rel} → {len(b)//1024} KB ({mime})")
    return f"data:{mime};base64," + base64.b64encode(b).decode("ascii")

def collect_paths(node, out):
    if isinstance(node, dict):
        for v in node.values():
            collect_paths(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_paths(v, out)
    elif isinstance(node, str) and IMG_RE.match(node.strip()):
        out.add(node.strip())

def load(name, default):
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        print(f"  ! 缺少 {name}，使用默认空值")
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def js(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # 防止数据中出现 </script> 提前关闭脚本块
    return s.replace("</", "<\\/")

def main():
    data    = load("data.json", {})
    guides  = load("guides.json", {}).get("guides", [])
    seasons = load("seasonGuides.json", {}).get("seasons", [])
    events  = load("events.json", {"categories": [], "events": []})
    rebirth = load("rebirthGuides.json", {}).get("guides", [])
    status  = load("data_status.json", {"level": "unknown", "issues": [], "provenance": {}})

    # 收集 data 中引用的本地图片，压缩后内联为 base64（保证单文件也能显示配图）
    paths = set()
    collect_paths(data, paths)
    assets_map = {}
    for rel in sorted(paths):
        uri = asset_uri(rel)
        if uri:
            assets_map[rel] = uri

    block = (
        "/* INLINE-DATA-START */\n"
        f"const INLINE_DATA = {js(data)};\n"
        f"const INLINE_GUIDES = {js(guides)};\n"
        f"const INLINE_SEASONS = {js(seasons)};\n"
        f"const INLINE_EVENTS = {js(events)};\n"
        f"const INLINE_REBIRTH_GUIDES = {js(rebirth)};\n"
        f"const INLINE_STATUS = {js(status)};\n"
        f"const INLINE_ASSETS = {js(assets_map)};\n"
        "/* INLINE-DATA-END */"
    )

    with open(HTML, encoding="utf-8") as f:
        html = f.read()

    pattern = re.compile(r"/\* INLINE-DATA-START \*/.*?/\* INLINE-DATA-END \*/", re.S)
    if not pattern.search(html):
        print("  ! 未找到 INLINE-DATA 标记，无法注入")
        sys.exit(1)
    html = pattern.sub(lambda m: block, html, count=1)

    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✓ 已内联：{len(seasons)} 季 / {len(events.get('events',[]))} 活动 / "
          f"{len(guides)} 条每日任务攻略 / {len(rebirth)} 条复刻图鉴 / data 字段 {len(data)} 个 / 本地图 {len(assets_map)} 张 / 健康状态 {status.get('level','?')}")
    print(f"  ✓ 输出：{HTML}（{os.path.getsize(HTML)//1024} KB）")

if __name__ == "__main__":
    main()
