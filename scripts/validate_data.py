#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
validate_data.py —— 光遇国服资讯「数据可靠性校验层」

在 fetch_data.py 抓完数据后运行，对 data.json 做三类检查：
  1) 抓取来源可追溯（provenance）：实时接口 / 攻略站文章 / 复刻 / 新季节
     各自成功还是失败；多个源同时挂掉直接报错。
  2) 多源交叉校验：实时接口(third-api) 与 攻略站文章对同一字段给出不同
     结论时告警 —— 重点防「落石：接口有实况图、文章却写『今日无落石』」
     这类历史误报（曾导致红石日误显示「今日无落石」）。
  3) 字段合理性单源校验：每日任务应为 4 条、大蜡烛地图须在已知集合、
     落石不能既无图又无文字说明、数据不能超 24h 不更新等。

产出 data_status.json（页面据此在顶部显示红/黄告警条），
同时向 stdout 打印一份可读报告，便于日志与人工巡检。
"""
import os, re, json, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 一律按北京时间判断（CI runner 为 UTC，避免"差一天"）
def now_cst():
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)

# 国服大蜡烛固定在这几个地图间轮替
KNOWN_MAPS = ["云野", "雨林", "霞谷", "暮土", "禁阁", "晨岛", "云巢"]

LEVEL_RANK = {"ok": 0, "warn": 1, "error": 2}


def _maps_from_api(candle_api):
    """['云野3','雨林2','暮土2'] -> ['云野','雨林','暮土']（去掉末尾情形编号）"""
    out = []
    for s in (candle_api or []):
        if not isinstance(s, str):
            continue
        m = re.match(r"^([\u4e00-\u9fa5]+?)\d*$", s.strip())
        if m:
            out.append(m.group(1))
    return out


def _maps_from_text(txt):
    txt = txt or ""
    parts = re.split(r"[\s、/，,；;]+", txt)
    maps = []
    for p in parts:
        for m in KNOWN_MAPS:
            if m in p:
                maps.append(m)
                break
    if not maps:  # 处理连写如「云野雨林暮土」
        for m in KNOWN_MAPS:
            if m in txt:
                maps.append(m)
    return maps


def run(data, art=None, prov=None, root=None):
    """对 data.json 做校验，写 data_status.json，返回 status 字典。

    art  : parse_daily() 得到的文章解析结果（用于交叉校验）
    prov : {'api','article','rebirth','season'} 取值 ok|fail|skip
    root : 输出目录（默认 /workspace）
    """
    root = root or ROOT
    data = data or {}
    prov = prov or {}
    t = data.get("today", {}) or {}
    issues = []

    def add(code, level, title, detail=""):
        issues.append({"code": code, "level": level, "title": title, "detail": detail})

    api = prov.get("api", "skip")
    article = prov.get("article", "skip")
    rebirth = prov.get("rebirth", "skip")
    season = prov.get("season", "skip")

    # ---------- 1) 抓取来源可追溯 ----------
    if article == "fail" and api != "ok":
        add("SOURCE_ALL_DOWN", "error",
            "全部数据源抓取失败",
            "实时接口与攻略站文章均未能获取，今日资讯可能缺失或过期，请检查网络 / 接口 Key。")
    if api == "fail" and article == "ok":
        add("API_DOWN_ARTICLE_FALLBACK", "warn",
            "实时接口暂不可用，已用文章兜底",
            "今日数据来自攻略站文章，可能比游戏内实际刷新延迟数小时。")
    if rebirth == "fail":
        add("REBIRTH_FETCH_FAIL", "warn",
            "复刻先祖信息抓取失败", "不影响今日任务/蜡烛，下次抓取会自动恢复。")
    if season == "fail":
        add("SEASON_FETCH_FAIL", "warn",
            "新季节信息抓取失败", "不影响今日任务/蜡烛，下次抓取会自动恢复。")

    # ---------- 2) 多源交叉校验 ----------
    fs = t.get("fallenStone") or {}
    fs_imgs = t.get("fallenStoneImages") or []
    loc = (fs.get("location") or "")
    # 落石自相矛盾：数据里有实况图，但地点文字却写「无落石」（经典误报）
    if fs_imgs and "无落石" in loc:
        add("STONE_CONFLICT", "error",
            "落石数据自相矛盾",
            "接口已返回今日红石/黑石实况图，但地点文字标注「今日无落石」，疑似未刷新到最新文章。请核对。")
    # 文章解析里写「无落石」但数据有图
    if art and (art.get("fallenStone") or {}).get("location"):
        aloc = art["fallenStone"].get("location", "")
        if fs_imgs and "无落石" in aloc and not any(i["code"] == "STONE_CONFLICT" for i in issues):
            add("STONE_CONFLICT", "error",
                "落石数据自相矛盾",
                "攻略站文章标注「今日无落石」，但实时接口返回了落石实况图，两者冲突，以前者为准可能有误。")

    # 大蜡烛地图：接口 vs 文章
    api_maps = _maps_from_api(t.get("candleApi") or [])
    art_maps = _maps_from_text(((art or {}).get("bigCandles") or {}).get("map", ""))
    if api_maps and art_maps and set(api_maps) != set(art_maps):
        add("CANDLE_MAP_CONFLICT", "warn",
            "大蜡烛地图接口与文章不一致",
            f"接口：{' / '.join(api_maps)}；文章：{' / '.join(art_maps)}。可能文章尚未更新到今日轮换。")

    # 每日任务：接口与文章措辞本就不同（同一任务两边描述各异），
    # 按字符串比对会天天误报，故只做「数量」合理性校验（见下方 TASK_COUNT），
    # 不在此做接口-文章任务文本的交叉比对。

    # 免费魔法：接口 vs 文章（按分隔符拆成集合比对，避免「/」与「、」造成误报）
    if api == "ok" and (t.get("freeMagic") or "").strip() and art and (art.get("freeMagic") or "").strip():
        a = {x.strip() for x in re.split(r"[/、,，]+", t["freeMagic"]) if x.strip()}
        b = {x.strip() for x in re.split(r"[/、,，]+", art["freeMagic"]) if x.strip()}
        if a and b and a != b:
            add("MAGIC_CONFLICT", "warn",
                "免费魔法接口与文章不一致",
                f"接口：{t['freeMagic']}；文章：{art['freeMagic']}。")

    # ---------- 3) 字段合理性单源校验 ----------
    tasks = t.get("dailyTasks") or []
    n = len(tasks)
    if n == 0:
        add("TASK_EMPTY", "error",
            "今日每日任务为空", "未能解析到任何每日任务，请检查数据源。")
    elif n != 4:
        add("TASK_COUNT", "warn",
            "每日任务数量异常", f"国服每日任务固定 4 条，本次解析到 {n} 条，可能解析不完整。")

    candle_api = t.get("candleApi") or []
    big = t.get("bigCandles") or {}
    if not candle_api and not (big.get("map") or "").strip():
        add("CANDLE_MISSING", "warn",
            "今日大蜡烛数据缺失", "接口与文章均未给出大蜡烛位置，建议重抓。")
    else:
        unknown = [m for m in api_maps if m not in KNOWN_MAPS]
        if unknown:
            add("CANDLE_UNKNOWN_MAP", "warn",
                "大蜡烛出现未知地图", f"接口给出未知地图名：{' / '.join(unknown)}，请核对。")

    # 落石缺失：既无实况图又无地点文字（明确「无落石」不算缺失）
    if not fs_imgs and not loc.strip():
        add("STONE_MISSING", "error",
            "今日落石数据缺失", "既无落石实况图也无地点说明，建议重抓或人工补充。")

    if not (t.get("freeMagic") or "").strip():
        add("MAGIC_EMPTY", "warn",
            "今日免费魔法为空", "部分日期确实无免费魔法，可忽略；若应有而空，请核对。")

    updated_ts = (data.get("meta") or {}).get("updatedTs")
    if updated_ts:
        try:
            ts = datetime.strptime(updated_ts, "%Y-%m-%dT%H:%M:%S")
            age_h = (now_cst() - ts).total_seconds() / 3600.0
            if age_h > 24:
                add("STALE", "warn",
                    "数据超过 24 小时未更新",
                    f"数据更新于 {updated_ts}，已超过 {int(age_h)} 小时未刷新，可能过期。")
        except Exception:
            pass

    sc = t.get("seasonCandles") or {}
    if sc.get("status") == "进行中" and not (sc.get("spots") or []):
        add("SEASON_CANDLE_NOSPOTS", "warn",
            "季节蜡烛状态矛盾", "标记为「进行中」但缺少位置信息，建议重抓。")

    # ---------- 汇总 ----------
    errors = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    level = "ok"
    if errors:
        level = "error"
    elif warns:
        level = "warn"
    summary = ("数据校验通过 ✓" if level == "ok"
               else f"{len(errors)} 项错误 / {len(warns)} 项警告，需关注")
    status = {
        "checkedAt": now_cst().strftime("%Y-%m-%dT%H:%M:%S"),
        "level": level,
        "summary": summary,
        "issues": issues,
        "provenance": {
            "api": api, "article": article, "rebirth": rebirth, "season": season,
        },
    }

    out_path = os.path.join(root, "data_status.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    # 可读报告
    print("\n========== 数据可靠性校验 ==========")
    print(f"  等级：{level.upper()}   检查项：{len(issues)}")
    print(f"  来源：接口={api} 文章={article} 复刻={rebirth} 新季节={season}")
    for i in sorted(issues, key=lambda x: -LEVEL_RANK[x["level"]]):
        tag = "✗" if i["level"] == "error" else "!"
        print(f"  {tag} [{i['code']}] {i['title']}"
              + (f" —— {i['detail']}" if i["detail"] else ""))
    if level == "ok":
        print("  ✓ 未发现异常，数据可信。")
    print(f"  已写回 {out_path}")
    return status


def run_cli():
    data_path = os.path.join(ROOT, "data.json")
    data = json.load(open(data_path, encoding="utf-8"))
    run(data, art=None, prov=None, root=ROOT)


if __name__ == "__main__":
    run_cli()
