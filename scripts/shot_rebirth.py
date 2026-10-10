#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 截图：复刻图鉴新功能的三个状态（今日页 / 攻略弹窗 / 季节徽标）。"""
import json, os, sys, time, subprocess, threading, urllib.request, websocket

CHROME="/usr/bin/chromium"
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL="file://"+os.path.join(ROOT,"index.html")
PORT=9344
OUT=ROOT

def req(u): return json.loads(urllib.request.urlopen(u,timeout=5).read().decode())

def main():
    proc=subprocess.Popen([CHROME,f"--remote-debugging-port={PORT}","--headless=new","--no-sandbox",
        "--disable-gpu","--disable-dev-shm-usage","--remote-allow-origins=*",
        "--user-data-dir=/tmp/sky_cdp_shot","--window-size=440,1400",
        "about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        ws_url=None
        for _ in range(40):
            try:
                ts=req(f"http://127.0.0.1:{PORT}/json/list")
                p=next((t for t in ts if t.get("type")=="page"),None)
                if p and p.get("webSocketDebuggerUrl"): ws_url=p["webSocketDebuggerUrl"]; break
            except Exception: time.sleep(0.25)
        ws=websocket.create_connection(ws_url,timeout=20)
        rid=[0]
        def send(m,p=None): rid[0]+=1; ws.send(json.dumps({"id":rid[0],"method":m,"params":p or {}})); return rid[0]
        def rec(i,t=15):
            e=time.time()+t
            while time.time()<e:
                ws.settimeout(e-time.time())
                try: mm=json.loads(ws.recv())
                except Exception: return None
                if mm.get("id")==i: return mm
        send("Page.enable"); send("Runtime.enable")
        n=send("Page.navigate",{"url":URL}); rec(n)
        time.sleep(2.6)
        def ev(x):
            i=send("Runtime.evaluate",{"expression":x,"awaitPromise":True,"returnByValue":True}); m=rec(i,10)
            return m["result"].get("result",{}).get("value") if m and "result" in m else None
        def shot(name):
            i=send("Page.captureScreenshot",{"format":"png"}); m=rec(i,10)
            if m and "result" in m:
                import base64; open(os.path.join(OUT,name),"wb").write(base64.b64decode(m["result"]["data"]))
                print("  saved",name)
        # 1) 今日页 近期复刻列表（含「攻略」标记）
        ev("var h=document.querySelector('.hist'); if(h) h.scrollIntoView({block:'center'});")
        time.sleep(0.5)
        shot("shot_today_rebirth.png")
        # 2) 点击近期复刻 → 攻略弹窗
        ev("(function(){var el=document.querySelector('.h-click'); if(el) el.click();})()")
        time.sleep(0.6)
        shot("shot_rebirth_guide.png")
        # 3) 关闭弹窗 → 季节页 → 滚到珍珠季「即将开启」徽标
        ev("closeRebirthGuide && closeRebirthGuide()")
        ev("(function(){ if(typeof switchTab==='function') switchTab('season');})()")
        time.sleep(0.5)
        ev("var b=document.querySelector('.season-mark.soon'); if(b) b.scrollIntoView({block:'center'});")
        time.sleep(0.5)
        shot("shot_season_badge.png")
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()

if __name__=="__main__": main()
