#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 验证：无头 Chromium 打开 index.html，核对复刻图鉴弹窗 / 季节徽标 / 无 JS 报错 / 无横向溢出。"""
import json, os, sys, time, subprocess, threading, urllib.request, websocket, argparse

CHROME = "/usr/bin/chromium"
URL = "file://" + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
PORT = 9333

def req(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode())

def main():
    # 启动无头浏览器
    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", "--headless=new", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
         "--user-data-dir=/tmp/sky_cdp_profile",
         "about:blank"],
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
            print("✗ 无法连接 CDP 页面目标"); sys.exit(1)

        ws = websocket.create_connection(ws_url, timeout=20)
        rid = [0]
        def send(method, params=None, _id=None):
            rid[0]+=1; i = _id or rid[0]
            ws.send(json.dumps({"id":i,"method":method,"params":params or {}}))
            return i
        def recv_id(i, timeout=15):
            end=time.time()+timeout
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
        t=threading.Thread(target=listen, daemon=True); t.start()

        send("Runtime.enable"); send("Page.enable")
        nav=send("Page.navigate", {"url": URL})
        recv_id(nav)
        time.sleep(2.5)  # 等渲染 + 内联数据就绪

        def ev(expr):
            i=send("Runtime.evaluate", {"expression": expr, "awaitPromise":True, "returnByValue":True})
            m=recv_id(i, 10)
            if m and "result" in m: return m["result"].get("result",{}).get("value")
            return None

        checks={}
        checks["REBIRTH_GUIDES_count"] = ev("typeof REBIRTH_GUIDES!=='undefined'?REBIRTH_GUIDES.length:-1")
        checks["showRebirthGuide_defined"] = ev("typeof showRebirthGuide")
        checks["recent_clickable_count"] = ev("document.querySelectorAll('.h-click').length")
        # 点击第一个可点击的近期复刻项，验证弹窗
        checks["modal_opened"] = ev("""(function(){
            var el=document.querySelector('.h-click'); if(!el) return 'no-el';
            el.click();
            var m=document.getElementById('rbModal');
            return m && m.classList.contains('show') ? 'open':'closed';
        })()""")
        checks["rb_items_count"] = ev("document.querySelectorAll('#rb-items .rb-item').length")
        checks["rb_name"] = ev("document.getElementById('rb-name').textContent")
        checks["rb_total"] = ev("document.getElementById('rb-total').textContent")
        # 关闭弹窗
        ev("closeRebirthGuide && closeRebirthGuide()")
        # 季节徽标
        checks["season_badge"] = ev("""(function(){
            if(typeof switchTab==='function') switchTab('season');
            var b=document.querySelector('.season-mark.soon');
            return b?b.textContent:'';
        })()""")
        # 横向溢出
        checks["overflow_x"] = ev("document.documentElement.scrollWidth - window.innerWidth")

        print("=== CDP 验证结果 ===")
        for k,v in checks.items():
            print(f"  {k}: {v}")
        print("=== JS 报错 ===")
        print("  " + ("无" if not errors else "\n  ".join(errors)))
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()

    ok = (checks.get("REBIRTH_GUIDES_count")==12 and checks.get("recent_clickable_count",0)>=1
          and checks.get("modal_opened")=="open" and checks.get("rb_items_count",0)>=3
          and checks.get("season_badge") and checks.get("overflow_x",999)<=2 and not errors)
    print("=== 结论 ===", "✓ 通过" if ok else "✗ 失败")
    sys.exit(0 if ok else 1)

if __name__=="__main__":
    main()
