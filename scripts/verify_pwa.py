#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 验证：线上 PWA 可安装性（Page.getInstallabilityState + getAppManifest）。"""
import json, os, sys, time, subprocess, urllib.request, websocket

CHROME = "/usr/bin/chromium"
URL = "https://lueyoyo1-afk.github.io/sky-daily/?cb=pwa1"
PORT = 9666

def req(u): return json.loads(urllib.request.urlopen(u, timeout=5).read().decode())

def main():
    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", "--headless=new", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
         "--user-data-dir=/tmp/sky_pwa_profile", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url=None
        for _ in range(40):
            try:
                t=req(f"http://127.0.0.1:{PORT}/json/list")
                p=next((x for x in t if x.get("type")=="page"),None)
                if p and p.get("webSocketDebuggerUrl"): ws_url=p["webSocketDebuggerUrl"]; break
            except Exception: time.sleep(0.25)
        if not ws_url: print("✗ 无 CDP"); sys.exit(1)
        ws=websocket.create_connection(ws_url, timeout=20)
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
        send("Runtime.enable"); send("Page.enable")
        send("Page.navigate", {"url": URL})
        time.sleep(7)
        # 可安装性状态
        i1=send("Page.getInstallabilityState"); r1=recv(i1,10)
        st = r1["result"] if r1 and "result" in r1 else {}
        # manifest
        i2=send("Page.getAppManifest"); r2=recv(i2,10)
        mf = r2["result"] if r2 and "result" in r2 else {}
        print("=== PWA 可安装性 ===")
        print("  isInstallable:", st.get("installableState" if "installableState" in st else "isInstallable", st))
        print("  manifest url:", mf.get("url"))
        print("  manifest errors:", mf.get("errors"))
        print("  manifest warnings:", mf.get("warnings"))
        pm = mf.get("parsed") or {}
        print("  name:", pm.get("name"), "| display:", pm.get("display"), "| scope:", pm.get("scope"))
        print("  icons:", [f"{ic.get('sizes')}({ic.get('purpose')})" for ic in (pm.get("icons") or [])])
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    sys.exit(0)

if __name__=="__main__":
    main()
