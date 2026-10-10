#!/usr/bin/env python3.11
"""
新活动 / 新季节 / 联动 -> 自动发现，无需人工维护 events.json

思路：
1. 扫 9game 光遇「游戏新闻」列表页，按标题关键词挑出活动 / 联动 / 季节类文章
   （每日任务攻略会被排除，那是 fetch_data.py 的活）
2. 对没见过的文章抓详情页，解析：发布时间、活动时间区间、代币名、地图、摘要
3. 去重（按文章 URL id）后写进 events.json，标 auto:true + source，页面即可直接展示
4. 顺带同步 data.json：新季节的开启日期、当前进行中的活动列表

幂等：重复跑只会更新 mete/static 字段，不会重复追加。
用法：
    python3.11 scripts/discover_events.py          # 只补最新
    python3.11 scripts/discover_events.py --all    # 连历史深处的文章也扫一遍
"""
import re, os, json, sys
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import fetch, mapkey, DATA  # noqa: E402

EVENTS = os.path.join(os.path.dirname(DATA), "events.json")
NEWS_LIST = "https://www.9game.cn/skygy/list_1/"

# ---------- 标题关键词 ----------
# 命中才算「活动/季节资讯」，避免把同人创作、返图、抽奖之类也拉进来
POS = [
    "联动", "代币", "活动攻略", "活动玩法", "兑换物品", "复刻先祖",
    "正式开启", "即将开启", "套装上线", "返场", "上线即得", "代币位置",
]
# 季节专属标题，形如「珍珠季·海底花园丨…」
SEASON_RE = re.compile(r"([\u4e00-\u9fa5]{2,6}季)\s*[·・]")
# 排除：日常任务、常驻攻略、杂项
NEG = ["每日任务", "馆藏", "图鉴", "预约", "礼包", "激活码",
       "玩法介绍", "价格", "新手", "下载", "礼包"]
JUNK_TITLE = ["参展返图", "参展回顾", "同人作品", "引路丨记录"]
# 只收最近 N 天发布的（历史旧帖由人工整理的那批负责）
RECENT_DAYS = 45

MAP_WORDS = [
    "星光海", "珍珠村", "海底花园", "月牙绿洲", "云巢", "遇境",
    "晨岛", "云野", "雨林", "霞谷", "暮土", "禁阁", "圣岛", "方舟",
]


def clean_title(t):
    """《光·遇》xxx -> xxx；去掉书名单引号尾巴"""
    t = re.sub(r"^《[^》]*》", "", t or "").strip()
    return t.rstrip("！!。. ")


def is_candidate(title):
    t = title or ""
    if any(n in t for n in NEG):
        return False
    if any(j in t for j in JUNK_TITLE):
        return False
    if SEASON_RE.search(t):
        return True
    return any(p in t for p in POS)


def scan_list():
    """返回 [(url, title)]，按文章 ID 从大到小"""
    html = fetch(NEWS_LIST)
    from bs4 import BeautifulSoup  # noqa: E402
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=re.compile(r"skygy/\d+\.html")):
        href = a.get("href") or ""
        title = (a.get("title") or a.get_text() or "").strip()
        if not title or not is_candidate(title):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif not href.startswith("http"):
            href = "https://www.9game.cn" + href
        aid = re.search(r"skygy/(\d+)\.html", href)
        if not aid or aid.group(1) in seen:
            continue
        seen.add(aid.group(1))
        out.append((int(aid.group(1)), href, title))
    out.sort(key=lambda x: -x[0])
    return [(aid, u, t) for aid, u, t in out]


# ---------- 详情页解析 ----------
def parse_detail(url, title):
    from bs4 import BeautifulSoup  # noqa: E402
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    text = re.sub(r"\s*\n\s*", "\n", text)

    published = None
    pm = re.search(r"发布时间[：:]\s*(20\d\d-\d\d-\d\d \d\d:\d\d:\d\d)", text)
    if pm:
        published = pm.group(1)

    # 正文：发布时间之后、"类型:"（游戏信息卡 / 评论区）之前
    body = ""
    i = text.find("发布时间")
    if i >= 0:
        tail = text[i:]
        j = tail.find("类型:")
        body = tail[: j if j > 0 else len(tail)]
    else:
        body = text[:2000]

    lines = []
    for ln in body.split("\n"):
        ln = ln.strip()
        if len(ln) < 6:
            continue
        if ln in ("上九游，领福利", "光遇", "下载") or re.match(r"^发布时间[：:]", ln) or ln.startswith("作者："):
            continue
        lines.append(ln)
    body = "\n".join(lines)

    # 名称 / 副标题：标题里常有 「珍珠季·海底花园丨随波摇曳 斑斓满园」
    name, subtitle = clean_title(title), ""
    for sep in ["丨", "|"]:
        if sep in name:
            a, b = name.split(sep, 1)
            name, subtitle = a.strip(), b.strip()
            break

    # 活动时间
    period, pstart, pend = None, None, None
    m = re.search(r"活动时间[：: ]*\s*([^\n]{4,40})", body)
    if m:
        period = m.group(1).strip()
    pm2 = re.search(r"(20\d\d|\d{1,2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})\s*[-~至到]\s*"
                    r"(20\d\d|\d{1,2})?[.\-/年]?(\d{1,2})[.\-/月](\d{1,2})", body)
    if pm2:
        y1, m1, d1, y2, m2, d2 = pm2.groups()
        try:
            pstart = datetime(int(y1) if len(y1) == 4 else 2000 + int(y1), int(m1), int(d1))
            pend = datetime(int(y2 or y1) if len(str(y2 or y1)) == 4 else 2000 + int(y2 or y1), int(m2), int(d2))
            period = f"{pstart:%Y-%m-%d} ~ {pend:%Y-%m-%d}"
        except Exception:
            pass
    sm = SEASON_RE.search(name)          # 季节文常用「将于 10月22日 开启」
    if not period and sm:
        mm = re.search(r"(\d{1,2})月(\d{1,2})日\s*开启", body)
        if mm:
            pstart = datetime(datetime.now().year, int(mm.group(1)), int(mm.group(2)))
            period = f"{pstart:%Y-%m-%d} 开启"

    # 代币名：出现次数最多的「XX代币」，排除泛词
    cur = None
    toks = Counter(re.findall(r"([\u4e00-\u9fa5]{2,6}代币)", body))
    bad = ("活动", "收集", "游戏", "有些", "这些", "这个")
    cand = [(n, c) for n, c in toks.items() if not any(b in n for b in bad)]
    if cand:
        cur = max(cand, key=lambda x: x[1])[0]

    # 地图
    mp = next((w for w in MAP_WORDS if w in (body + name)), None)

    # 摘要：优先用带句号的正文，拿不到就回落到「正文 + 原文」拼一段
    intro_lines = [l for l in lines if not re.match(r"^(活动时间|代币位置|货币兑换|注：)", l)][:2]
    intro = " ".join(intro_lines).strip()
    if len(intro) < 24:
        tail = [l for l in lines if l not in intro_lines][:2]
        intro = (" ".join(intro_lines + tail)).strip() or "官方发布新资讯，点击下方查看原文攻略。"
    if "." not in intro and "。" not in intro:
        intro += "（以上为官方原文节选，完整玩法请查看原文攻略）"

    return {
        "name": name,
        "subtitle": subtitle,
        "period": period,
        "pstart": pstart,
        "pend": pend,
        "currency": cur,
        "map": mp,
        "intro": intro,
        "publishedAt": published,
        "body": body[:1200],
    }


def classify(name, body):
    if re.search(r"([\u4e00-\u9fa5]{2,6}季)\s*[·・]", name) or "新季节" in name:
        return "collabSeason"
    if "联动" in name or "联动" in body[:200]:
        return "collabEvent"
    return "festival"


def status_of(pstart, pend, now):
    if pend and pend < now:
        return "已结束"
    if pstart and pstart > now:
        return "即将开始"
    if pstart and (not pend or pend >= now):
        return "进行中"
    return "预告"


def main(scan_all=False):
    now = datetime.now()
    ev = json.load(open(EVENTS, encoding="utf-8"))
    data = json.load(open(DATA, encoding="utf-8"))
    known_src = {(e.get("source") or "") for e in ev["events"]}
    known_key = {e.get("key") for e in ev["events"]}

    try:
        arts = scan_list()
    except Exception as e:
        print("列表抓取失败:", e)
        return 1
    if not scan_all:
        arts = arts[:12]          # 只看最近一批，历史深处不追（省流且避免噪音）

    added, skipped, skipped_old = 0, 0, 0
    for aid, url, title in arts:
        key = f"auto-{aid}"
        if url in known_src or key in known_key:
            skipped += 1
            continue
        try:
            d = parse_detail(url, title)
        except Exception as e:
            print("  跳过", url, "->", e)
            continue
        # 太旧的资讯不收（历史部分已在人工整理的那批里）
        if d["publishedAt"]:
            try:
                pub = datetime.strptime(d["publishedAt"], "%Y-%m-%d %H:%M:%S")
                if (now - pub).days > RECENT_DAYS:
                    skipped_old += 1
                    continue
            except Exception:
                pass
        # 没有解析到活动时间时，回落到 data.json 里已知的季节开启日
        if not d["period"]:
            kwd = (data.get("season") or {}).get("name") or ""
            sstart = (data.get("season") or {}).get("start")
            if kwd and kwd in d["name"] and sstart:
                d["period"] = sstart[:10] + " 开启"
                try:
                    d["pstart"] = datetime.strptime(sstart, "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    pass
        cat = classify(d["name"], d["body"])
        st = status_of(d["pstart"], d["pend"], now)
        entry = {
            "key": key,
            "category": cat,
            "name": d["name"],
            "subtitle": d["subtitle"],
            "period": d["period"] or (d["publishedAt"][:10] if d["publishedAt"] else "时间待公布"),
            "status": st,
            "map": d["map"] or "待公布",
            "mapKey": mapkey(d["map"] or ""),
            "entry": "详见原文攻略",
            "intro": d["intro"],
            "auto": True,
            "source": url,
            "publishedAt": d["publishedAt"],
            "currency": {"name": d["currency"], "rules": "详见原文", "howTo": []} if d["currency"] else None,
            "items": [],
        }
        # 插到同分类最前面，新活动一出现就排在最显眼的位置
        idx = next((i for i, e in enumerate(ev["events"]) if e.get("category") == cat), None)
        ev["events"].insert(idx if idx is not None else len(ev["events"]), entry)
        known_src.add(url)
        known_key.add(key)
        added += 1
        print(f"  + 新发现 [{cat}] {d['name']} | {st} | {d['period']} | {url}")

        # 顺带同步 data.json
        if cat == "collabSeason" and d["pstart"]:
            cur_start = (data.get("season") or {}).get("start")
            if not cur_start or d["pstart"].strftime("%Y-%m-%dT%H:%M:%S") > cur_start:
                data["season"] = {
                    "name": d["name"].split("·")[0],
                    "start": d["pstart"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "preheat": None,
                    "maps": [w for w in MAP_WORDS if w in d["body"]][:3],
                    "items": [],
                    "source": url,
                }
                print("    → 更新 data.json 新季节:", data["season"]["name"], data["season"]["start"])
        if st == "进行中":
            acts = data.get("activities") or []
            if not any(a.get("name") == d["name"] for a in acts):
                acts.append({
                    "name": d["name"],
                    "start": d["pstart"].strftime("%Y-%m-%dT%H:%M:%S") if d["pstart"] else None,
                    "end": d["pend"].strftime("%Y-%m-%dT%H:%M:%S") if d["pend"] else None,
                    "tokenToday": 0,
                    "tokenNote": "详见活动页 / 原文攻略",
                    "status": "进行中",
                    "auto": True,
                    "source": url,
                })
                data["activities"] = acts
                print("    → 加入进行中活动:", d["name"])

    # 清理过期活动（结束超 30 天的不再占据主卡片）
    keep, dropped = [], 0
    for a in data.get("activities") or []:
        end = a.get("end")
        try:
            if end and datetime.strptime(end, "%Y-%m-%dT%H:%M:%S") < now.replace(hour=0) and (now - datetime.strptime(end, "%Y-%m-%dT%H:%M:%S")).days > 30:
                dropped += 1
                continue
        except Exception:
            pass
        keep.append(a)
    data["activities"] = keep
    if dropped:
        print(f"  · 清理已结束活动 {dropped} 条")

    # 「NEW」标记：只给最近 3 天自动发现来的条目，重跑会自动过期
    for e in ev["events"]:
        if not e.get("auto"):
            continue
        try:
            pub = datetime.strptime(e["publishedAt"], "%Y-%m-%d %H:%M:%S")
            e["isNew"] = (now - pub).days <= 3
        except Exception:
            e["isNew"] = False

    ev["meta"]["updatedAt"] = now.strftime("%Y-%m-%d")
    json.dump(ev, open(EVENTS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ events.json 现有 {len(ev['events'])} 条"
          f"（新增 {added}，已存在跳过 {skipped}，超 {RECENT_DAYS} 天的旧帖忽略 {skipped_old}）")
    return 0


if __name__ == "__main__":
    sys.exit(main("--all" in sys.argv))
