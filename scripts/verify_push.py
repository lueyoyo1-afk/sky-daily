#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 验证：线上 https 站点的 Web Push 前端可用性。"""
import json, os, sys, time, subprocess, threading, urllib.request, websocket

CHROME = "/usr/bin/chromium"
URL = "https://lueyoyo1-afk.github.io/sky-daily/"
PORT = 9555

def req(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode())

def main():
    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", "--headless=new", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
         "--user-data-dir=/tmp/sky_push_profile", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(40):
            try:
                targets = req(f"http://127.0.0.1:{PORT}/json/list")
                page = next((t for t in targets if t.get("type")=="page"), None)
                if page and page.get("webSocketDebuggerUrl"):
                    ws_url = page["webSocketDebuggerUrl"]; break
            except Exception:
                time.sleep(0.25)
        if not ws_url:
            print("✗ 无法连接 CDP"); sys.exit(1)
        ws = websocket.create_connection(ws_url, timeout=20)
        rid=[0]
        def send(m,p=None):
            rid[0]+=1; i=rid[0]; ws.send(json.dumps({"id":i,"method":m,"params":p or {}})); return i
        def recv(i,t=15):
            end=time.time()+t
            while time.time()<end:
                ws.settimeout(end-time.time())
                try: m=json.loads(ws.recv())
                except Exception: return None
                if m.get("id")==i: return m
            return None
        errors=[]
        def listen():
            while True:
                try: ws.settimeout(1.0); m=json.loads(ws.recv())
                except Exception: break
                if m.get("method")=="Runtime.exceptionThrown":
                    err=m["params"]["exceptionDetails"]
                    errors.append(err.get("text","")+" "+(err.get("exception",{}).get("description","") or ""))
        threading.Thread(target=listen, daemon=True).start()
        send("Runtime.enable"); send("Page.enable")
        send("Page.navigate", {"url": URL})
        time.sleep(8)
        def ev(expr):
            i=send("Runtime.evaluate", {"expression": expr, "awaitPromise":True, "returnByValue":True})
            m=recv(i,10)
            return m["result"]["result"]["value"] if m and "result" in m else None

        checks={}
        checks["title"]        = ev("document.title")
        checks["pushBtn_visible"] = ev("(function(){var b=document.getElementById('pushBtn'); return b? (getComputedStyle(b).display!=='none') : 'no-btn';})()")
        checks["pushBtn_title"]   = ev("(document.getElementById('pushBtn')||{}).title||''")
        checks["PUSH_CFG_set"]    = ev("typeof PUSH_CFG!=='undefined' && !!PUSH_CFG.vapid")
        checks["togglePush_fn"]   = ev("typeof togglePush")
        checks["sw_registered"]   = ev("navigator.serviceWorker.getRegistration('./').then(r=>r?'registered':'none').catch(e=>'err:'+e)")
        checks["overflow_x"]      = ev("document.documentElement.scrollWidth - window.innerWidth")
        print("=== 线上 Web Push 前端检查 ===")
        for k,v in checks.items(): print(f"  {k}: {v}")
        print("=== JS 报错 ===")
        print("  " + ("无" if not errors else "\n  ".join(errors)))
        ok=(checks.get("title")=="光遇 · 每日资讯"
            and checks.get("pushBtn_visible") is True
            and checks.get("PUSH_CFG_set") is True
            and checks.get("togglePush_fn")=="function"
            and checks.get("sw_registered")=="registered"
            and checks.get("overflow_x",999)<=2
            and not errors)
        print("=== 结论 ===", "✓ 通过" if ok else "✗ 失败")
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    sys.exit(0 if ok else 1)

if __name__=="__main__":
    main()
