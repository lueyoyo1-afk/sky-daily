#!/usr/bin/env python3.11
"""
光遇国服资讯聚合脚本（混合方案的「自动聚合」部分）
- 复刻先祖：抓取 duotegame 国服复刻文章，解析先祖名/赛季/时间/物品
- 真实每日任务：抓取 9game 国服每日任务文字（替代示例/OCR，作为默认数据源）
- 新季节：抓取 ali213 等新季节资讯（如珍珠季）
- OCR（运营上传真实微博图）为可选，见 ocr_tasks.py，默认不跑以免覆盖真实源
- 全部写入 data.json；单模块失败不影响其他模块，保留线上数据

定时运行示例（每天 07:00）：
  0 7 * * * cd /workspace && python3.11 scripts/fetch_data.py >> logs/fetch.log 2>&1
"""
import re, json, os, sys
from datetime import datetime, timedelta
import urllib.request
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import sky_api          # 第三方实时接口（可选，装了 key 才生效）
except Exception:
    sky_api = None
import validate_data        # 数据可靠性校验层（无外部依赖，必可用）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根目录（本地=/workspace，CI=检出目录）
DATA = os.path.join(ROOT, "data.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
YEAR = 2026
WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 复刻文章种子源（下个复刻发生后替换为最新文章 URL 即可）
REBIRTH_SOURCES = ["https://www.duotegame.com/mgl/225744.html"]

# 9game 国服每日任务「列表页」——每天自动发现最新的「每日任务」文章，无需手动换 URL
DAILY_LIST = "https://www.9game.cn/skygy/list_1/"
# 种子回退（首跑或列表不可用时使用，指向已知最新每日任务文章）
DAILY_SEED_URL = "https://www.9game.cn/skygy/12123621.html"

# 新季节资讯源（ali213 珍珠季）
SEASON_SOURCES = ["https://app.ali213.net/gl/1814567.html"]

# 地图中文名 -> 前端 SVG 示意图 key（供季蜡 / 大蜡烛配图使用）
MAPKEY = [
    ("星光海", "pearl"), ("珍珠村", "pearl"), ("海底花园", "pearl"),
    ("月牙", "yueya"), ("绿洲", "yueya"),
    ("晨岛", "chendao"), ("云野", "yunye"), ("雨林", "yulin"),
    ("霞谷", "xiagu"), ("暮土", "mutu"), ("禁阁", "jinge"),
    ("云巢", "yunchao"), ("遇境", "yujing"), ("方舟", "mutu"), ("圣岛", "yunye"),
]

def mapkey(name):
    for k, v in MAPKEY:
        if k in (name or ""):
            return v
    return None


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="ignore")


# ---------- 复刻先祖 ----------
def parse_rebirth(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text() if soup.title else ""
    text = soup.get_text("\n")
    m = re.search(r'光遇\d+月\d+日(.+?)先祖复刻', title)
    ancestor = m.group(1).strip() if m else None
    s = re.search(r'【(.+?季)】', text)
    season = s.group(1) if s else ""
    d = re.search(r'(\d+)月(\d+)日\s*早6:00\s*-\s*(\d+)月(\d+)日\s*中午12:00', text)
    start = end = None
    if d:
        sm, sd, em, ed = map(int, d.groups())
        start = datetime(YEAR, sm, sd, 6, 0)
        end = datetime(YEAR, em, ed, 12, 0)
    items = []
    im = re.search(r'复刻物品[:：]\s*([^\n]+)', text)
    if im:
        items = [x.strip() for x in re.split(r'[/、，, ]', im.group(1)) if x.strip()]
    return {
        "ancestor": (season + " · " + ancestor) if (season and ancestor) else (ancestor or "未知"),
        "season": season,
        "start": start.strftime("%Y-%m-%dT%H:%M:%S") if start else None,
        "end": end.strftime("%Y-%m-%dT%H:%M:%S") if end else None,
        "items": items,
        "source": url,
    }


def compute_next(start_iso):
    s = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S")
    return (s + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")  # 国服通常两周一复刻


# ---------- 每日任务列表自动发现（9game 国服） ----------
def discover_daily_url():
    """从 list_1 列表页发现最新「每日任务」文章 URL。
    列表页为 SSR、带 title，且每日持续更新；取 title 含'每日任务'且 ID 最大的链接。"""
    try:
        html = fetch(DAILY_LIST)
        soup = BeautifulSoup(html, "html.parser")
        best, best_id, best_title = None, -1, ""
        for a in soup.find_all("a", href=re.compile(r"skygy/\d+\.html$")):
            title = a.get("title") or ""
            href = a.get("href") or ""
            if "每日任务" in title:
                m = re.search(r"skygy/(\d+)\.html", href)
                if m:
                    aid = int(m.group(1))
                    if aid > best_id:
                        best_id, best, best_title = aid, href, title
            if best:
                url = best if best.startswith("http") else "https://www.9game.cn" + best
                print("自动发现最新每日任务文章:", url, "| title 命中")
                return url, best_title
        print("列表页未命中每日任务文章，将回退种子")
    except Exception as e:
        print("每日任务列表自动发现失败:", e, "-> 回退种子")
    return None


# ---------- 站方标题 → 攻略讲的是「哪一天」 ----------
# 标题形如《光·遇》10.9每日任务攻略！ —— 国服 00:00 刷新，
# 数据日期必须以「这篇攻略讲的是哪一天」为准，而不是脚本运行时刻，
# 否则站方凌晨抢发 / 晚上提前发次日任务时，页面会误判成"过期"。
TITLE_DAY_RE = re.compile(r"(\d{1,2})[.．・、/月](\d{1,2})")


def title_day(title, now):
    m = TITLE_DAY_RE.search(title or "")
    if not m:
        return None
    mo, dd = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12 and 1 <= dd <= 31):
        return None
    cand = datetime(now.year, mo, dd)
    diff = (cand.date() - now.date()).days
    if diff > 1:        # 跨年：标题月比当前月大很多 → 属于上一年
        cand = datetime(now.year - 1, mo, dd)
    elif diff < -1:
        cand = datetime(now.year + 1, mo, dd)
    if abs((cand.date() - now.date()).days) > 1:
        return None
    return cand


# ---------- 真实每日任务（9game 国服） ----------
def parse_daily(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    out = {"dailyTasks": [], "fallenStone": None, "freeMagic": None,
           "bigCandles": None, "scheduleNote": None, "seasonCandles": None,
           "workshopNote": None}

    # 任务：截取【每日任务】之后、评论/大蜡烛/魔法之前
    m = re.search(r'【每日任务】(.*?)(?:初一看|海妖天|今日大蜡烛|◎|落石点|魔法工坊|常规免费)', text, re.S)
    seg = m.group(1) if m else ""
    if not seg:
        m2 = re.search(r'每日任务(.*?)(?:落石|大蜡烛|魔法)', text, re.S)
        seg = m2.group(1) if m2 else ""
    # 优先提取「」/『』内的任务名
    names = re.findall(r'\d+[、．.]\s*[「『]?([^「『」』\n]{2,30}?)[」』]', seg)
    if not names:
        names = re.findall(r'\d+[、．.]\s*([^0-9\n]{2,24})', seg)
    tasks = [n.strip(' 、.。」』「『').strip() for n in names if n.strip()]
    out["dailyTasks"] = [t for t in tasks if len(t) >= 2][:4]

    # 落石点：文章格式为「『落石点』\n位置:XX 性质:红石 时间:...」或「今日无落石」
    sm = re.search(r'落石点[】）】』\s]*\n?([\s\S]{0,140}?)(?:\n『|日程提醒|魔法工坊|今日季节|今日大蜡|每日任务|附|$)', text)
    if sm:
        blk = sm.group(1)
        if "无落石" in blk or re.search(r'今日无', blk):
            out["fallenStone"] = {"location": "今日无落石", "type": "-", "times": []}
        else:
            loc = re.search(r'(?:位置|地点)[：:]\s*([^\n、，]{1,30})', blk)
            typ = re.search(r'性质[：:]\s*([^\n、，]{1,10})', blk)
            tim = re.search(r'时间[：:]\s*([^\n]{1,80})', blk)
            out["fallenStone"] = {
                "location": (loc.group(1).strip() if loc
                             else (blk.strip().split("\n")[0][:30])),
                "type": (typ.group(1).strip() if typ else "-"),
                "times": ([s.strip() for s in re.split(r'[、,，]', tim.group(1)) if s.strip()]
                          if tim else []),
            }

    # 免费魔法 / 限免
    fm = re.search(r'(?:今日魔法商店限免|常规免费魔法)[：:]\s*([^\n]{0,40})', text)
    if fm:
        out["freeMagic"] = fm.group(1).strip()

    # 日程提醒（如：双倍心火、全图大蜡烛进行中）
    sm2 = re.search(r'日程提醒[」』】）]?\s*\n?\s*([^\n]{0,60})', text)
    if sm2:
        out["scheduleNote"] = sm2.group(1).strip()

    # 筑巢工坊家具周更（第 N/13 周）
    wm = re.search(r'这是第\s*(\d+)\s*/\s*13\s*周', text)
    if wm:
        out["workshopNote"] = f"筑巢工坊家具每周一刷新；本周为 13 周轮替的第 {wm.group(1)}/13 周"

    # 今日大蜡烛位置
    bm = re.search(r'今日大蜡烛位置[」』】）]?\s*\n?\s*([^\n（(]{1,24})', text)
    if bm:
        mp = bm.group(1).strip()
        out["bigCandles"] = {"map": mp, "mapKey": mapkey(mp)}

    # 季节蜡烛（季蜡）：季节进行中文章才会给出 4 处位置
    cm = re.search(r'今日(?:季节蜡烛|季蜡)位置[」』】）]?\s*\n?\s*([\s\S]{0,400})', text)
    if not cm:
        cm = re.search(r'(?:季蜡|季节蜡烛)[：:]\s*\n?\s*([\s\S]{0,300})', text)
    if cm:
        seg = cm.group(1)
        mp = None
        mm = re.search(r'(云野|雨林|霞谷|暮土|禁阁|晨岛|云巢|遇境|星光海|珍珠村|月牙绿洲)', seg)
        if mm:
            mp = mm.group(1)
        spots = [s.strip(" 、.\n") for s in re.findall(r'\d+[、．.]\s*([^\n]{2,40})', seg)]
        spots = [s for s in spots if len(s) >= 2][:4]
        out["seasonCandles"] = {
            "status": "进行中",
            "map": mp or "该季地图",
            "mapKey": mapkey(mp or ""),
            "spots": spots,
            "note": "季节蜡烛每天在该季地图刷新 4 处，收集可得季节蜡烛。",
        }
    return out


# ---------- 新季节（ali213 等） ----------
def parse_season(html, url):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    name = None
    for cand in ["珍珠季", "迁徙季", "珍宝季", "狂欢季", "织光季", "致梵谷", "青鸟季", "彩染季", "姆明季", "二重奏季", "归巢季", "筑巢季"]:
        if cand in text:
            name = cand
            break
    start = None
    s_match = re.search(r'(\d+)月(\d+)日\s*正式开启', text)
    if s_match:
        start = datetime(YEAR, int(s_match.group(1)), int(s_match.group(2)), 0, 0)
    preheat = None
    p_match = re.search(r'(?:预热已于)?(\d+)月(\d+)日\s*上线', text)
    if p_match:
        pm, pd = int(p_match.group(1)), int(p_match.group(2))
        if not s_match or (pm, pd) != (int(s_match.group(1)), int(s_match.group(2))):
            preheat = f"{YEAR}-{pm:02d}-{pd:02d}"
    items = list(dict.fromkeys(re.findall(r'(珍珠斗篷|贝壳头饰|鱼尾裙|船锚背饰|海浪面具|鹿角|叶片斗篷|蝴蝶触角)', text)))
    maps = list(dict.fromkeys(re.findall(r'(星光海|珍珠村|漫游狂欢号|灯笼存放所)', text)))
    if not name and not start:
        return None
    return {
        "name": name or "新季节",
        "start": start.strftime("%Y-%m-%dT00:00:00") if start else None,
        "preheat": preheat,
        "maps": maps,
        "items": items,
        "source": url,
    }


def try_api_first(data):
    """先试第三方实时接口（跟着游戏 00:00 刷新，最快）。
    拿不到就返回 False，交给 9game 文章抓取兜底。"""
    if not sky_api or not sky_api.has_key():
        return False
    print("[API] 已配置 KEY，优先取第三方实时数据……")
    try:
        got = sky_api.fetch_all(verbose=False)
    except Exception as e:
        print("[API] 调用异常:", e, "-> 回落到文章抓取")
        return False
    if not got.get("ok"):
        print("[API] 失败:", got.get("err"), "-> 回落到文章抓取")
        return False
    # 图片端点（任务位置图/活动日历/复刻位置图）直接返回 JPEG，下载到本地 assets/
    img_paths = {}
    try:
        img_paths = sky_api.download_api_images(sky_api.load_key(), ROOT)
    except Exception as e:
        print("[API] 图片下载跳过:", e)
    # 大蜡位置图（dlwz 里的 CDN 直链，无需 key）也下载到本地 assets/
    try:
        big_urls = (got.get("candle") or {}).get("images") or []
        got["bigCandleImages"] = sky_api.download_image_list(big_urls, ROOT)
    except Exception as e:
        print("[API] 大蜡图下载跳过:", e)
    # 落石/红石位置图（gytq 里的 CDN 直链，含官方「今日天气预报」）下载到本地 assets/
    try:
        stone_urls = got.get("stoneImages") or []
        got["fallenStoneImages"] = sky_api.download_image_list(stone_urls, ROOT, prefix="stone")
    except Exception as e:
        print("[API] 落石图下载跳过:", e)
    changed = sky_api.apply_to_data(data, got, img_paths)
    if not changed:
        print("[API] 没解析出可用内容 -> 回落到文章抓取")
        return False
    print("[API] 拿到:", "、".join(changed))
    return True


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    now = datetime.now()

    # 今日日期动态生成；若站方标题给出具体那天，以站方为准（见下方 2）
    target = now

    # 1) 复刻先祖
    results = []
    for url in REBIRTH_SOURCES:
        try:
            r = parse_rebirth(fetch(url), url)
            if r["start"]:
                results.append(r)
                print("复刻解析成功:", r["ancestor"], r["start"], "~", r["end"], "| 物品:", r["items"])
        except Exception as e:
            print("复刻抓取失败", url, "->", e)
    if results:
        results.sort(key=lambda x: x["start"], reverse=True)
        latest = results[0]
        if latest["end"] and datetime.strptime(latest["end"], "%Y-%m-%dT%H:%M:%S") > now:
            data["currentRebirth"] = latest
            data["lastRebirth"] = None
        else:
            data["lastRebirth"] = latest
            data["currentRebirth"] = None
        data["nextRebirthForecast"] = {
            "ancestor": "（预测）下一位复刻先祖",
            "season": "待官方官宣",
            "start": compute_next(latest["start"]),
            "forecast": True,
        }

    prov["rebirth"] = "ok" if results else "fail"

    # 2) 真实每日任务（优先第三方实时接口，失效再回退 9game 文章）
    prov = {"api": "skip", "article": "skip", "rebirth": "skip", "season": "skip"}
    daily_url = data.get("lastDailyUrl") or DAILY_SEED_URL
    api_ok = try_api_first(data)
    api_configured = bool(sky_api and sky_api.has_key())
    prov["api"] = "ok" if api_ok else ("fail" if api_configured else "skip")

    # 无论 API 成功与否，都尝试发现「当天」的文章：
    #   落石点/日程提醒/季蜡 等字段 API 拿不到文字，只能靠文章；
    #   但必须确认文章确实是「今天」的，否则昨天文章会把今天的落石/日程带偏
    #   （典型：10.9 文章写「今日无落石」，被误用到 10.10 红石日）。
    found = discover_daily_url()
    art_is_today = False
    if found:
        art_day = title_day(found[1], now)
        if art_day is not None and art_day.date() == now.date():
            daily_url, art_is_today = found[0], True
            data["lastDailyUrl"] = daily_url
            print("发现当天文章:", daily_url, "|", found[1])
        elif not api_ok:
            # API 也失败：退用最新一篇文章，保证任务/资讯仍有内容
            daily_url = found[0]
            data["lastDailyUrl"] = daily_url
            if art_day:
                target = art_day
                print("站方标题 → 攻略目标日期:", target.strftime("%Y-%m-%d"), "|", found[1])
    elif not api_ok:
        daily_url = DAILY_SEED_URL
        data["lastDailyUrl"] = daily_url

    # 数据的「今天」= 这篇攻略讲的那一天（国服 00:00 刷新）
    data["today"]["dateLabel"] = f"{target.year}年{target.month}月{target.day}日 {WEEK[target.weekday()]}"
    # use_article：文章的「正文类」字段（落石/日程/工坊/季蜡）是否可信
    #             —— 是当天文章，或 API 挂了必须靠文章兜底
    use_article = art_is_today or (not api_ok)
    art = None
    try:
        d = parse_daily(fetch(daily_url))
        art = d
        prov["article"] = "ok"
        # 只有 API 没给当天任务时，才用 9game 文章的任务（避免覆盖 00:00 实时数据）
        if d["dailyTasks"] and data["today"].get("dailyTasksSource") != "api":
            data["today"]["dailyTasks"] = d["dailyTasks"]
            data["today"]["dailyTasksSource"] = "real"
            print("每日任务(真实) 来源", daily_url, ":", d["dailyTasks"])
        # 落石：API 给的是「图」（权威、0 点自动更新）；文章只可能给文字。
        # 仅当文章是当天的、且给出真实地点（非「无落石」）时才用它补充文字；否则保留图片。
        if d["fallenStone"] and use_article:
            loc = d["fallenStone"].get("location") or ""
            real_loc = bool(loc) and ("无落石" not in loc)
            if real_loc or not data["today"].get("fallenStoneImages"):
                data["today"]["fallenStone"] = d["fallenStone"]
                print("落石(文章):", d["fallenStone"].get("location"),
                      "|", d["fallenStone"].get("type"), "|", d["fallenStone"].get("times"))
        # 以下字段 API 优先，仅在 API 失败时用文章兜底
        if d["freeMagic"] and not api_ok:
            data["today"]["freeMagic"] = d["freeMagic"]
        if d["bigCandles"] and not api_ok:
            data["today"]["bigCandles"] = d["bigCandles"]
            print("今日大蜡烛位置:", d["bigCandles"]["map"], "| 配图key:", d["bigCandles"]["mapKey"])
        # 日程 / 工坊 / 季蜡：仅当文章是当天的（或 API 挂了）才采用
        if d["scheduleNote"] and use_article:
            data["today"]["scheduleNote"] = d["scheduleNote"]
        if d.get("workshopNote") and use_article:
            data["today"]["workshopNote"] = d["workshopNote"]
            print("工坊周更:", d["workshopNote"])
        if d["seasonCandles"] and use_article:
            data["today"]["seasonCandles"] = d["seasonCandles"]
            print("季蜡(真实):", d["seasonCandles"]["map"], d["seasonCandles"]["spots"])
    except Exception as e:
        print("每日任务抓取失败:", e)
        prov["article"] = "fail"

    # 季节蜡烛：抓不到真实 4 处位置时，按当前季节状态给出说明
    sc = data["today"].get("seasonCandles")
    if (not sc) or (not sc.get("spots")):
        s = data.get("season") or {}
        sname = s.get("name") or "新季节"
        smaps = s.get("maps") or []
        smap = " / ".join(smaps) if smaps else "该季地图"
        sstart = s.get("start")
        started = False
        try:
            started = bool(sstart and datetime.strptime(sstart, "%Y-%m-%dT%H:%M:%S") <= now)
        except Exception:
            started = False
        if sstart and not started:
            note = (f"当前为季节空窗期（上个季节已结束），暂无季节蜡烛。"
                    f"{sname} 将于 {sstart[:10]} 开启，开启后季蜡会每天在【{smap}】刷新 4 处，"
                    f"届时本页会自动更新为真实位置。")
            status = "空窗期"
        else:
            note = f"暂未抓取到今日季蜡位置；通常季蜡会在当季地图【{smap}】刷新 4 处。"
            status = "未获取"
        data["today"]["seasonCandles"] = {
            "status": status, "map": smap, "mapKey": mapkey(smap),
            "spots": [], "note": note,
        }

    # 3) 新季节
    season_ok = False
    for url in SEASON_SOURCES:
        try:
            s = parse_season(fetch(url), url)
            if s:
                data["season"] = s
                season_ok = True
                print("新季节:", s["name"], s.get("start"), "预热", s.get("preheat"), "| 地图", s.get("maps"))
                break
        except Exception as e:
            print("季节抓取失败", url, "->", e)
    prov["season"] = "ok" if season_ok else "fail"

    # updatedAt = 数据所属的「游戏日」（和 00:00 刷新保持一致）
    # updatedTs = 真实抓取时刻（页面用它算"多久以前"）
    data["meta"]["updatedAt"] = target.strftime("%Y-%m-%d")
    data["meta"]["updatedTs"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已写回 data.json  updatedAt=%s  抓取于=%s  dateLabel=%s" % (
        data["meta"]["updatedAt"], data["meta"]["updatedTs"], data["today"].get("dateLabel")))

    # 往日任务归档：每次刷新把「今天的任务」快照追加进 history.json（按日期去重，保留最近 90 天）
    try:
        HISTORY = os.path.join(ROOT, "history.json")
        snap = {
            "date": data["meta"]["updatedAt"],
            "dailyTasks": data["today"].get("dailyTasks", []) or [],
            "bigCandles": (data["today"].get("bigCandles") or {}).get("map", ""),
            "freeMagic": data["today"].get("freeMagic", "") or "",
            "source": data["today"].get("dailyTasksSource", "") or "",
        }
        hist = {"days": []}
        if os.path.exists(HISTORY):
            try:
                with open(HISTORY, encoding="utf-8") as fh:
                    hist = json.load(fh)
                if not isinstance(hist.get("days"), list):
                    hist["days"] = []
            except Exception:
                hist = {"days": []}
        hist["days"] = [x for x in hist["days"] if x.get("date") != snap["date"]]
        hist["days"].append(snap)
        hist["days"].sort(key=lambda x: x["date"])
        hist["days"] = hist["days"][-90:]
        with open(HISTORY, "w", encoding="utf-8") as fh:
            json.dump(hist, fh, ensure_ascii=False, indent=2)
        print("已追加历史快照:", snap["date"], "| 历史天数:", len(hist["days"]))
    except Exception as e:
        print("历史快照写入失败:", e)

    # 数据可靠性校验：接口/文章交叉比对 + 字段合理性，写 data_status.json（供页面告警）
    try:
        validate_data.run(data, art=art, prov=prov, root=ROOT)
    except Exception as e:
        print("数据校验异常（不影响落库）:", e)


if __name__ == "__main__":
    main()
