#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓单页截图：python3.11 shot_page.py <tab> <out.png> [width]"""
import json, os, sys, time, subprocess, threading, urllib.request, websocket, base64

CHROME = "/usr/bin/chromium"
URL = "file:///workspace/index.html"
PORT = 9777

def req(u): return json.loads(urllib.request.urlopen(u, timeout=5).read().decode())

def main():
    tab = sys.argv[1] if len(sys.argv) > 1 else "today"
    out = sys.argv[2] if len(sys.argv) > 2 else f"shot_{tab}.png"
    w = sys.argv[3] if len(sys.argv) > 3 else "420"
    proc = subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", "--headless=new",
        "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
        f"--window-size={w},900", "--user-data-dir=/tmp/sky_shot_profile", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url=None
        for _ in range(40):
            try:
                t=req(f"http://127.0.0.1:{PORT}/json/list")
                p=next((x for x in t if x.get("type")=="page"),None)
                if p and p.get("webSocketDebuggerUrl"): ws_url=p["webSocketDebuggerUrl"]; break
            except Exception: time.sleep(0.25)
        ws=websocket.create_connection(ws_url, timeout=20); rid=[0]
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
        send("Page.enable"); send("Runtime.enable")
        send("Page.navigate", {"url": URL}); time.sleep(7)
        send("Runtime.evaluate", {"expression": f"switchTab && switchTab('{tab}',{{noScroll:true}})", "awaitPromise":True})
        time.sleep(1.2)
        # 打印该页关键元素的盒模型，帮助定位"顶头"
        probe = """(function(){
          var pg=document.querySelector('#page-%s'); if(!pg) return 'no-page';
          var r=pg.getBoundingClientRect();
          var q=function(sel){var e=pg.querySelector(sel); if(!e) return null;
            var b=e.getBoundingClientRect(); var cs=getComputedStyle(e);
            return {sel:sel,left:Math.round(b.left),padL:cs.paddingLeft,marL:cs.marginLeft};};
          return JSON.stringify({page_left:Math.round(r.left), items:[q('.evt-group-t'),q('.evt-card'),q('.evt-nm'),q('.evt-grid')]});
        })()""" % tab
        i=send("Runtime.evaluate", {"expression": probe, "returnByValue":True})
        m=recv(i,10)
        print("BOX:", m["result"]["result"]["value"] if m and "result" in m else "?")
        i=send("Page.captureScreenshot", {"format":"png"})
        m=recv(i,10)
        with open(os.path.join("/workspace", out), "wb") as f:
            f.write(base64.b64decode(m["result"]["data"]))
        print("SAVED", out)
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()

if __name__=="__main__":
    main()
