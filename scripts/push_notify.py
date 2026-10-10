#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""每日推送：读 data.json 组装摘要，调用 Supabase Edge Function push-send 推送给所有订阅者。

在 GitHub Actions 每日 fetch+build 后运行。需要环境变量 PUSH_SEND_TOKEN（存为仓库 secret）。
推送失败不影响部署（工作流里用 || true 兜底）。
"""
import json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data.json")
FN_URL = "https://mdkvbklgkmwtfscderrc.functions.supabase.co/push-send"
SITE = "https://lueyoyo1-afk.github.io/sky-daily/"


def compose(d):
    t = d.get("today", {})
    parts = []
    # 大蜡烛地图（candleApi 如 ["云野3","雨林2","暮土2"]，取地图名）
    maps = []
    for s in (t.get("candleApi") or []):
        m = re.match(r"^([\u4e00-\u9fa5]+)", str(s))
        if m:
            maps.append(m.group(1))
    if maps:
        parts.append("大蜡烛：" + "·".join(maps))
    # 落石
    fs = t.get("fallenStone") or {}
    loc = (fs.get("location") or "").strip()
    if loc and "无落石" not in loc:
        times = "、".join((fs.get("times") or [])[:3])
        parts.append(f"落石：{loc}" + (f"（{times}）" if times else ""))
    elif t.get("fallenStoneImages"):
        parts.append("落石：见页内实况图")
    # 免费魔法
    fm = (t.get("freeMagic") or "").strip()
    if fm:
        parts.append(f"免费魔法：{fm}")
    # 本周复刻
    cr = d.get("currentRebirth")
    if cr and cr.get("ancestor"):
        parts.append(f"本周复刻：{cr['ancestor']}")
    return "；".join(parts) if parts else "今日资讯已更新，点击查看"


def main():
    token = os.environ.get("PUSH_SEND_TOKEN", "")
    if not token:
        print("[push] 未配置 PUSH_SEND_TOKEN，跳过")
        return 0
    try:
        d = json.load(open(DATA, encoding="utf-8"))
    except Exception as e:
        print("[push] 读 data.json 失败:", e)
        return 0
    body = compose(d)
    payload = json.dumps({
        "title": "光遇 · 每日资讯已更新",
        "body": body,
        "url": SITE,
        "tag": "sky-daily",
    }).encode("utf-8")
    req = urllib.request.Request(FN_URL, data=payload, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("[push] 推送结果:", r.status, r.read().decode("utf-8")[:300])
    except Exception as e:
        print("[push] 调用失败:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
