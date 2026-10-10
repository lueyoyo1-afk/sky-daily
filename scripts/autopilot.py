#!/usr/bin/env python3.11
"""
0 点自动更新守护 —— 真正保证「过了 0 点内容就换」

为什么需要它：
  光遇国服每日任务 / 季蜡 / 大蜡烛都是 **00:00** 刷新，但攻略站发布时间不固定
  （有的凌晨就发，有的拖到早上）。只靠一天跑一次的 cron，很可能整天都是昨天的。
  这个守护会：
    1. 跨到新的一天 -> 立刻抓一轮
    2. 拿到的还不是今天的 -> 每 HUNT_MIN 分钟重试一次，直到成功
    3. 已经是今天的 -> 降频到 IDLE_MIN 分钟一次（抓站方提前发的「次日攻略」）
    4. 只有内容真的变了才重建 index.html 的内联数据

用法：
    python3.11 scripts/autopilot.py            # 常驻守护（推荐）
    python3.11 scripts/autopilot.py --once     # 只跑一轮就退出（配合 cron 用）
    python3.11 scripts/autopilot.py --once --force   # 无视是否已最新，强制抓
"""
import os, sys, json, time, subprocess, argparse
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "logs")
DATA = os.path.join(ROOT, "data.json")
EVENTS = os.path.join(ROOT, "events.json")
LOCK = os.path.join(LOGS, "autopilot.lock")
PY = sys.executable or "python3.11"

IDLE_MIN = 30      # 数据已是今天时的巡检间隔
HUNT_MIN = 10      # 数据还是昨天时的追新间隔
IG = ("meta", "updatedTs")   # 比较内容时忽略的字段


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(os.path.join(LOGS, "autopilot.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def snapshot():
    """返回剔除了抓取时间戳的内容快照，用于判断「有没有真的变」"""
    out = {}
    for name, path in (("data", DATA), ("events", EVENTS)):
        try:
            j = json.load(open(path, encoding="utf-8"))
            if name == "data":
                j.get("meta", {}).pop("updatedTs", None)
            out[name] = json.dumps(j, ensure_ascii=False, sort_keys=True)
        except Exception:
            out[name] = ""
    return out


def run_step(script, args=()):
    cmd = [PY, os.path.join(ROOT, "scripts", script), *args]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
        tail = (r.stdout or "").strip().splitlines()[-3:]
        for ln in tail:
            log(f"  · {script}: {ln}")
        if r.returncode != 0:
            log(f"  ! {script} 退出码 {r.returncode}")
        return r.returncode == 0
    except Exception as e:
        log(f"  ! {script} 执行失败: {e}")
        return False


def is_fresh():
    """data.json 里的攻略是不是「今天」的"""
    try:
        return json.load(open(DATA, encoding="utf-8"))["meta"]["updatedAt"] == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def update_once(force=False):
    before = snapshot()
    if not force and is_fresh():
        # 已是今天：只补 activities / season 这类低频变化
        log("已经是今天的数据，只做增量巡检")
        run_step("discover_events.py")
    else:
        log("开始抓取每日任务……")
        run_step("fetch_data.py")
        log("开始扫描新活动 / 新季节……")
        run_step("discover_events.py")

    after = snapshot()
    changed = before["data"] != after["data"] or before["events"] != after["events"]
    if changed:
        log("内容有更新 -> 重建 index.html 内联数据")
        run_step("build_inline.py")
    else:
        log("内容与上次一致，跳过重建")
    return changed, is_fresh()


def seconds_until_next_day():
    nxt = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return max(5, (nxt - datetime.now()).total_seconds())


def sleep_until_next_day():
    sec = seconds_until_next_day()
    log(f"数据已是最新，休眠到明日 00:00（{int(sec//3600)} 小时 {int(sec%3600//60)} 分后自动开抓）")
    time.sleep(sec)


def loop():
    os.makedirs(LOGS, exist_ok=True)
    # 文件锁：避免同时开两个守护
    try:
        import fcntl
        fp = open(LOCK, "w")
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
    except Exception as e:
        log(f"已有守护在运行（{e}），本次退出")
        return 1

    today = datetime.now().date()
    log("=" * 60)
    log("守护启动：00:00 自动刷新每日任务 / 活动 / 新季节")

    while True:
        day = datetime.now().date()
        if day != today:
            log(f"跨到新的一天 {day} -> 立即抓取")
            today = day
        try:
            changed, fresh = update_once()
        except Exception as e:
            log(f"更新异常: {e}")
            fresh = False

        if fresh:
            # 已拿到今天的：睡到明天 0 点，但中途低频巡检一次（可能已发了明天的）
            nap = IDLE_MIN * 60
            sec_to_midnight = seconds_until_next_day()
            if sec_to_midnight <= nap:
                log(f"距 00:00 只剩 {int(sec_to_midnight)} 秒，直接在 0 点后开抓")
                time.sleep(sec_to_midnight + 2)
            else:
                time.sleep(nap)
        else:
            log(f"还没拿到今天的任务，{HUNT_MIN} 分钟后重试")
            nap = HUNT_MIN * 60
            if seconds_until_next_day() <= nap:
                time.sleep(seconds_until_next_day() + 2)
            else:
                time.sleep(nap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--force", action="store_true", help="忽略「已是最新」判断，强制抓取")
    a = ap.parse_args()
    if a.once:
        update_once(force=a.force)
        return 0
    return loop()


if __name__ == "__main__":
    sys.exit(main())
