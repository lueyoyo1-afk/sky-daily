#!/usr/bin/env python3.11
"""
光遇国服实时数据 —— 第三方聚合 API 接入层

为什么需要它：
  这些接口的数据由攻略组维护，**跟着游戏侧 00:00 一起刷新**，
  不像攻略站文章要等编辑早上起床发文。拿到当天任务的速度从"几小时"变成"即时"。

数据源：应天 API（api.t1qq.com），免费申请 key -> https://api.t1qq.com/user/key
（接口结构稳定、免费、带配图；vqqc/ovoav 等镜像证书或路径不稳，暂不接入。）

可用端点（均已确认）：
  gyrw  每日任务文字              02 lzwz 大蜡烛/季蜡位置
  scrw  每日任务位置图（配图！）   03 scfk 先祖复刻位置图
  mf    今日免费魔法              04 djs  季节剩余倒计时
  gytq  红石/黑石天气（落石）     05 hdrl 活动日历图

本模块做「宽容解析」：不同服务商字段名可能叫 rw / data / list / result，
统一按「取看起来像任务的中文短句」来处理，结构怎么变都不至于全崩。
"""
import os, re, json, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(ROOT, "config", "api.env")

# 主服务商（免费申请 key -> https://api.t1qq.com/user/key）
PROVIDERS = {
    "t1qq": "https://api.t1qq.com/api/sky/",
}

# 端点路径
ENDPOINTS = {
    "tasks":   "gyrw",            # 每日任务文字（JSON）
    "candle":  "sc/lzwz",         # 大蜡烛 / 季蜡位置（JSON，含 img）
    "magic":   "mf/mf",           # 今日免费魔法（JSON）
    "stone":   "gytq",            # 红石 / 黑石天气（JSON）
    "countdown": "sc/gf/djs",     # 季节剩余倒计时（JSON）
}

# 以下三个端点「直接返回 JPEG 二进制」（不是 JSON）：
#   taskPic 每日任务位置图 / calendar 活动日历图 / rebirth 复刻位置图
# 处理办法：下载到本地 assets/，页面引用本地路径 —— 既不泄露 key，也不在每次
# 打开页面时消耗接口配额。
#   key 是端点名；value[0] 是接口路径；value[1] 是落地文件名（不含扩展名）
IMAGE_ENDPOINTS = {
    "taskPic":  ("sc/scrw", "taskpic"),   # -> assets/taskpic.jpg
    "calendar": ("sc/hdrl", "calendar"),  # -> assets/calendar.jpg
    "rebirth":  ("sc/scfk", "rebirth"),   # -> assets/rebirth.jpg
}

TASK_MAX = 40
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# ---------------- key 管理 ----------------
def load_key():
    """优先环境变量，其次 config/api.env"""
    k = os.environ.get("SKY_API_KEY", "").strip()
    if k:
        return k
    try:
        for ln in open(KEY_FILE, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k2, v = ln.split("=", 1)
                if k2.strip() in ("SKY_API_KEY", "KEY"):
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def has_key():
    return bool(load_key())


# ---------------- 请求 ----------------
def api_get(provider, endpoint, key, timeout=15):
    path = ENDPOINTS.get(endpoint, endpoint)
    url = PROVIDERS[provider] + path + "?key=" + urllib.parse.quote(key)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="ignore")
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}


def try_all(endpoint, timeout=15):
    """依次尝试各家服务商，返回 (provider, data, err)"""
    key = load_key()
    if not key:
        return None, None, "未配置 SKY_API_KEY"
    errs = []
    for p in list(PROVIDERS):
        try:
            j = api_get(p, endpoint, key, timeout)
        except Exception as e:
            errs.append(f"{p}: {e}")
            continue
        if isinstance(j, dict) and str(j.get("code")) not in ("200", "1", "0"):
            errs.append(f"{p}: {j.get('msg') or j.get('code')}")
            continue
        return p, j, None
    return None, None, "; ".join(errs[:2])


# ---------------- 图片端点（返回二进制 JPEG） ----------------
def image_url(endpoint, key):
    """图片端点本身就是一张图，URL 即资源地址（含 key，仅服务端使用）。"""
    info = IMAGE_ENDPOINTS.get(endpoint)
    if not info:
        return None
    return PROVIDERS["t1qq"] + info[0] + "?key=" + urllib.parse.quote(key)


def fetch_image_bytes(endpoint, key, timeout=20):
    """请求图片端点，返回 (content_type, bytes)。失败抛异常由调用方兜底。"""
    url = image_url(endpoint, key)
    if not url:
        raise ValueError("未知图片端点: " + str(endpoint))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "") or ""
        body = r.read()
    return ctype, body


def _ext_of(body):
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if body[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if body[:4] == b"GIF8":
        return ".gif"
    if body[:4] == b"RIFF":
        return ".webp"
    return ".jpg"


def download_api_images(key, root, verbose=True):
    """把三个图片端点下载到 root/assets/，返回 {endpoint: 相对路径}。
    任一项失败（429 / 网络 / 返回非图片）都不影响其他项，也不影响文本数据。"""
    import os
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)
    out = {}
    for ep, (path, fname) in IMAGE_ENDPOINTS.items():
        try:
            ctype, body = fetch_image_bytes(ep, key)
        except Exception as e:
            if verbose:
                print(f"  ✗ {ep} 图片下载失败: {e}")
            continue
        if not body or len(body) < 256:
            if verbose:
                print(f"  ✗ {ep} 返回空或过小（{len(body) if body else 0} 字节），跳过")
            continue
        ext = _ext_of(body)
        rel = f"assets/{fname}{ext}"
        with open(os.path.join(root, rel), "wb") as f:
            f.write(body)
        out[ep] = rel
        if verbose:
            print(f"  ✓ {ep} 图（{len(body)} 字节，{ctype or '?'}) -> {rel}")
    return out


def download_image_list(urls, root, prefix="bigcandle", verbose=True):
    """下载一组图片 URL（CDN 直链，无需 key）到 root/assets/，返回相对路径列表。
    顺序与输入一致，失败的项用 None 占位（便于与地图一一对应）。"""
    import os
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)
    out = []
    for i, u in enumerate(urls or []):
        if not isinstance(u, str) or not u.startswith("http"):
            out.append(None)
            continue
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
        except Exception as e:
            if verbose:
                print(f"  ✗ {prefix}图 {i+1} 下载失败: {e}")
            out.append(None)
            continue
        if not body or len(body) < 256:
            out.append(None)
            continue
        # 统一转 JPEG：这些是照片类位置图，原图是 PNG，内联后体积过大
        ext = ".jpg"
        try:
            from PIL import Image
            import io as _io
            im = Image.open(_io.BytesIO(body)).convert("RGB")
            buf = _io.BytesIO()
            im.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
            body = buf.getvalue()
        except Exception:
            ext = _ext_of(body)
        rel = f"assets/{prefix}{i+1}{ext}"
        with open(os.path.join(root, rel), "wb") as f:
            f.write(body)
        out.append(rel)
        if verbose:
            print(f"  ✓ {prefix}图 {i+1}（{len(body)} 字节）-> {rel}")
    return out


# ---------------- 宽容解析 ----------------
CN = re.compile(r"[\u4e00-\u9fa5]")
IMG_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp)(\?|$)", re.I)


def parse_candle(j):
    """解析 sc/lzwz：把「大蜡烛(dlwz)」与「季节蜡烛(jlwz)」彻底分开，避免混用。

    返回 {"big": {"maps": [...], "images": [...]}, "season": {...}}

    重要：maps 形如 ["云野3","雨林2","暮土2"]，其中的数字是该地图当日大蜡烛的
    「情形编号」(1-3)，**不是数量**；每个有大蜡烛的地图固定刷新 4 处。
    """
    out = {"big": {"maps": [], "images": []}, "season": {"maps": [], "images": []}}
    if not isinstance(j, dict):
        return out
    for src_key, kind in (("dlwz", "big"), ("jlwz", "season")):
        v = j.get(src_key)
        if not isinstance(v, dict):
            continue
        txt = v.get("text")
        if isinstance(txt, str):
            txt = [txt]
        if isinstance(txt, list):
            out[kind]["maps"] = [t.strip() for t in txt if isinstance(t, str) and t.strip()]
        imgs = v.get("img")
        if isinstance(imgs, str):
            imgs = [imgs]
        if isinstance(imgs, list):
            out[kind]["images"] = [u for u in imgs if isinstance(u, str) and u.startswith("http")]
    return out


def looks_like_task(s):
    s = (s or "").strip()
    if not s or len(s) > TASK_MAX or len(s) < 3:
        return False
    if not CN.search(s):
        return False
    bad = ("成功", "失败", "接口", "密钥", "http", "本站", "查询")
    return not any(b in s for b in bad)


def collect_texts(obj, out=None):
    """递归收集所有像任务的中文短句（兼容嵌套字典 / 列表，结构随意变化都不崩）"""
    if out is None:
        out = []
    if isinstance(obj, str):
        if looks_like_task(obj):
            out.append(obj.strip())
    elif isinstance(obj, list):
        for x in obj:
            collect_texts(x, out)
    elif isinstance(obj, dict):
        # 已知列表字段名优先（避免把整段说明也当成任务）
        for k in ("rw", "data", "list", "result", "tasks", "content", "info"):
            if k in obj and isinstance(obj[k], (list, dict)):
                collect_texts(obj[k], out)
        for v in obj.values():
            if isinstance(v, str) and looks_like_task(v):
                out.append(v.strip())
            elif isinstance(v, (dict, list)):
                collect_texts(v, out)   # 递归进嵌套结构
    # 去重保序
    seen, res = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            res.append(s)
    return res


def pick_tasks(j, limit=4):
    """优先按 rw[].text 这类结构取，失败再兜底全量扫描"""
    if not isinstance(j, dict):
        return []
    for key in ("rw", "data", "list", "result", "tasks"):
        v = j.get(key)
        if isinstance(v, list) and v:
            got = collect_texts(v)
            if got:
                return got[:limit]
    got = collect_texts({k: v for k, v in j.items() if k not in ("code", "msg", "from", "exec_time", "ip", "_raw")})
    return got[:limit]


def pick_magic(j, limit=6):
    """免费魔法：只取 magic[].text 这类列表结构，避开顶层标题字段（如 mf="今日免费魔法"）。"""
    if not isinstance(j, dict):
        return collect_texts(j)[:limit]
    for key in ("magic", "mf", "list", "data", "result"):
        v = j.get(key)
        if isinstance(v, list) and v:
            got = collect_texts(v)
            if got:
                return got[:limit]
    return []


def pick_images(j, limit=6):
    """递归取出所有图片 URL"""
    res = []

    def walk(o):
        if isinstance(o, str):
            if o.startswith("http") and IMG_EXT.search(o):
                res.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(j)
    seen, out = set(), []
    for u in res:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


def pick_field(j, names, limit=None):
    """按字段名模糊取值"""
    res = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                lk = str(k).lower()
                if any(n in lk for n in names) and isinstance(v, (str, int, float)):
                    res.append(str(v))
                elif any(n in lk for n in names) and isinstance(v, list):
                    res.extend([str(x) for x in v if isinstance(x, (str, int, float))])
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(j)
    return res[:limit] if limit else res


# ---------------- 对外：一次拿全 ----------------
def fetch_all(verbose=True):
    """返回 dict，任何一项失败都置 None，不影响其他项"""
    if not has_key():
        return {"ok": False, "err": "未配置 SKY_API_KEY"}
    out = {"ok": True, "source": {}, "raw": {}}
    plan = [
        ("tasks",    "tasks",    "每日任务"),
        ("candle",   "candle",   "大蜡/季蜡"),
        ("magic",    "magic",    "免费魔法"),
        ("stone",    "stone",    "红石天气"),
        ("countdown", "countdown", "季节倒计时"),
    ]
    for ep, kind, label in plan:
        p, j, err = try_all(ep)
        if err or j is None:
            if verbose:
                print(f"  ✗ {label}: {err}")
            continue
        out["raw"][ep] = j
        out["source"][ep] = p
        if kind == "tasks":
            out["tasks"] = pick_tasks(j)
        elif kind == "candle":
            parsed = parse_candle(j)
            out["candle"] = parsed["big"]           # 大蜡烛（dlwz）
            out["seasonCandle"] = parsed["season"]  # 季节蜡烛（jlwz）
        elif kind == "magic":
            out["magic"] = pick_magic(j)
        elif kind == "stone":
            # 该端点只返回「图片」（官方今日天气预报 + 位置截图），通常没有文字字段；
            # 图里已含今日红石/黑石的地图与点位，下载后前端直接展示（0 点自动更新）。
            out["stone"] = collect_texts(j)[:8]
            out["stoneImages"] = [
                u for u in (j.get("data") or [])
                if isinstance(u, str) and re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)
            ]
        elif kind == "countdown":
            out["countdown"] = collect_texts(j)[:8]
        if verbose:
            if kind == "candle":
                big = out.get("candle") or {}
                sea = out.get("seasonCandle") or {}
                print(f"  ✓ {label}（{p}）-> 大蜡图 {len(big.get('maps', []))} 个"
                      f" / 季蜡图 {len(sea.get('images', []))} 张")
            else:
                key = {"tasks": "tasks", "magic": "magic",
                       "stone": "stone", "countdown": "countdown"}[kind]
                n = len(out.get(key, []) or [])
                print(f"  ✓ {label}（{p}）-> {n} 条")
    return out


def apply_to_data(data, got, img_paths=None):
    """把 API 结果写进 data.json 结构；有值才覆盖，避免把旧数据冲成空。

    img_paths: download_api_images() 返回的 {endpoint: 相对路径}，本地图片。
    """
    if not got or not got.get("ok"):
        return []
    img_paths = img_paths or {}
    changed = []
    t = data.setdefault("today", {})

    tasks = got.get("tasks") or []
    # 过滤掉明显不是任务的兜底串（如 API 名、说明）
    tasks = [x for x in tasks if looks_like_task(x)][:4]
    if len(tasks) >= 3:
        t["dailyTasks"] = tasks
        t["dailyTasksSource"] = "api"
        changed.append(f"每日任务 {len(tasks)} 条")

    # 任务位置图：来自本地下载（不泄露 key）
    if img_paths.get("taskPic"):
        t["taskImages"] = [img_paths["taskPic"]]
        changed.append("任务位置图")

    # 大蜡烛：dlwz（如 云野3 / 雨林2 / 暮土2）。数字是「情形编号」不是数量，
    # 每个有大蜡烛的地图固定 4 处。
    cd = got.get("candle") or {}
    if isinstance(cd, dict) and cd.get("maps"):
        t["candleApi"] = cd["maps"]
        changed.append("大蜡烛 %d 图" % len(cd["maps"]))

    # 大蜡位置图：由 fetch_data.py 下载到本地后的相对路径
    big_imgs = [x for x in (got.get("bigCandleImages") or []) if x]
    if big_imgs:
        t["bigCandleImages"] = big_imgs
        changed.append("大蜡位置图 %d 张" % len(big_imgs))

    # 季节蜡烛：jlwz（仅季节进行期间有意义；空窗期前端不展示）
    scd = got.get("seasonCandle") or {}
    if isinstance(scd, dict) and scd.get("images"):
        t["seasonCandlesImage"] = scd["images"][0]
        changed.append("季蜡位置图")

    mg = got.get("magic") or []
    if mg:
        t["freeMagic"] = " / ".join([x for x in mg if x][:3])
        changed.append("免费魔法")

    # 落石/红石：以 gytq 返回的「官方实时图」为权威来源（0 点自动更新，图内含地图与点位）。
    simgs = [x for x in (got.get("fallenStoneImages") or []) if x]
    if simgs:
        t["fallenStoneImages"] = simgs
        # 清掉可能残留的旧文字（如昨天的「今日无落石」），避免与真实图片自相矛盾
        t["fallenStone"] = {"location": "", "type": "", "times": [], "source": "api-image"}
        changed.append("落石位置图 %d 张" % len(simgs))
    st = got.get("stone") or []
    if st:
        head = " ".join(st[:3])
        t["fallenStone"] = {"location": head[:40], "type": "API", "times": [], "source": "api-text"}
        changed.append("红石/黑石")

    # 活动日历图：来自本地下载
    if img_paths.get("calendar"):
        data["calendarImage"] = img_paths["calendar"]
        changed.append("活动日历图")

    # 复刻位置图：来自本地下载
    if img_paths.get("rebirth") and data.get("currentRebirth"):
        data["currentRebirth"]["image"] = img_paths["rebirth"]
        changed.append("复刻位置图")

    cdown = got.get("countdown") or []
    if cdown:
        data["seasonCountdown"] = " ".join(cdown[:3])
        changed.append("季节倒计时")

    if changed:
        data.setdefault("meta", {})["dailySource"] = "third-api:" + ",".join(sorted(set(got["source"].values())))
    return changed


if __name__ == "__main__":
    if "--dump" in __import__("sys").argv:
        import sys
        for ep in ENDPOINTS:
            p, j, err = try_all(ep)
            print(f"===== {ep} ({p or '×'}) err={err}")
            if j is not None:
                print(json.dumps(j, ensure_ascii=False)[:900])
    else:
        g = fetch_all()
        print(json.dumps({k: v for k, v in g.items() if k != "raw"}, ensure_ascii=False, indent=1))
