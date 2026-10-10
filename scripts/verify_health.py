#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 验证：数据健康告警条。
   1) 正常态（data_status=ok）：header 绿点 + healthBar 为空；
   2) 注入合成错误 STATUS：红条出现、条目数正确；
   3) 注入合成警告 STATUS：黄条出现；
   4) 截图 + 无 JS 报错 + 无横向溢出。"""
import json, os, sys, time, subprocess, threading, urllib.request, websocket, base64

CHROME = "/usr/bin/chromium"
URL = "file://" + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
PORT = 9444
SHOT_OK  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shot_health_ok.png")
SHOT_ERR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shot_health_error.png")
SHOT_WARN= os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shot_health_warn.png")

def req(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode())

def main():
    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", "--headless=new", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
         "--window-size=420,900",
         "--user-data-dir=/tmp/sky_health_profile",
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
        def send(method, params=None):
            rid[0]+=1; i=rid[0]
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
        time.sleep(2.8)

        def ev(expr):
            i=send("Runtime.evaluate", {"expression": expr, "awaitPromise":True, "returnByValue":True})
            m=recv_id(i, 10)
            if m and "result" in m: return m["result"].get("result",{}).get("value")
            return None
        def shot(path):
            i=send("Page.captureScreenshot", {"format":"png"})
            m=recv_id(i,10)
            if m and "result" in m:
                with open(path,"wb") as f:
                    f.write(base64.b64decode(m["result"]["data"]))
                print(f"  ✓ 截图 {os.path.basename(path)}")

        checks={}
        # 1) 正常态
        checks["dot_class_ok"]   = ev("document.getElementById('healthDot').className")
        checks["bar_empty_ok"]  = ev("document.getElementById('healthBar').innerHTML.trim()===''")
        checks["status_level"]  = ev("STATUS?STATUS.level:'undef'")
        shot(SHOT_OK)

        # 2) 注入合成错误态：落石自相矛盾 + 接口失败
        ev("""(function(){
          STATUS={
            level:'error',
            summary:'1 项错误 / 1 项警告，需关注',
            checkedAt:'2026-10-10T12:46:00',
            provenance:{api:'fail',article:'ok',rebirth:'ok',season:'ok'},
            issues:[
              {code:'STONE_CONFLICT',level:'error',title:'落石数据自相矛盾',detail:'接口已返回今日红石实况图，但文章文字标注「今日无落石」，疑似未刷新到最新文章。'},
              {code:'API_DOWN_ARTICLE_FALLBACK',level:'warn',title:'实时接口暂不可用，已用文章兜底',detail:'今日数据来自攻略站文章，可能比游戏内实际刷新延迟数小时。'}
            ]
          };
          renderHealth();
        })()""")
        time.sleep(0.5)
        checks["dot_class_err"]      = ev("document.getElementById('healthDot').className")
        checks["bar_has_error"]      = ev("document.getElementById('healthBar').querySelector('.stale.error')!==null")
        checks["bar_issue_count"]    = ev("document.getElementById('healthBar').querySelectorAll('.hi').length")
        checks["bar_first_title"]    = ev("(document.getElementById('healthBar').querySelector('.ht')||{}).textContent")
        shot(SHOT_ERR)

        # 3) 注入合成警告态
        ev("""(function(){
          STATUS={
            level:'warn',
            summary:'1 项警告，需关注',
            checkedAt:'2026-10-10T12:46:00',
            provenance:{api:'ok',article:'ok',rebirth:'fail',season:'ok'},
            issues:[
              {code:'REBIRTH_FETCH_FAIL',level:'warn',title:'复刻先祖信息抓取失败',detail:'不影响今日任务/蜡烛，下次抓取会自动恢复。'}
            ]
          };
          renderHealth();
        })()""")
        time.sleep(0.5)
        checks["dot_class_warn"] = ev("document.getElementById('healthDot').className")
        checks["bar_has_warn"]   = ev("document.getElementById('healthBar').querySelector('.stale.warn')!==null")
        shot(SHOT_WARN)

        # 4) 还原 + 溢出
        ev("STATUS=INLINE_STATUS||{level:'ok'}; renderHealth();")
        checks["overflow_x"] = ev("document.documentElement.scrollWidth - window.innerWidth")

        print("=== CDP 验证结果（数据健康告警） ===")
        for k,v in checks.items():
            print(f"  {k}: {v}")
        print("=== JS 报错 ===")
        print("  " + ("无" if not errors else "\n  ".join(errors)))

        ok = (checks.get("dot_class_ok","").endswith("ok")
              and checks.get("bar_empty_ok") is True
              and checks.get("dot_class_err","").endswith("err")
              and checks.get("bar_has_error") is True
              and checks.get("bar_issue_count",0)==2
              and checks.get("dot_class_warn","").endswith("warn")
              and checks.get("bar_has_warn") is True
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
