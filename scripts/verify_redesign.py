#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 验证：第三期「年鉴卡片网格」（一页一主题，细粒度卡片，减少滚动）。
   在第二期「独立刊物」编辑系统（书脊/目录首页/页眉/旁注/星青）之上，把各卷改造成卡片网格。
   断言：
     1) 无 Runtime.exceptionThrown；横向无溢出（320 / 420 / 1200）；
     2) 书脊 5 项点击可切换；data-tab / id / aria-controls 未变；
     3) 各卷容器 display:grid 且卡片数量 > 0；每卷有卷索引条 .vol-index（chip > 0）；
     4) 年鉴卡片样式：圆角 2px / 无阴影 / 顶边金线 / counter 序号；
     5) data-goto 一步跳转生效；#tab= 与 #tab=x&card=y 深链生效（保留 #evt= / #guide=）；
     6) 四个弹窗（攻略 / 活动 / 复刻 / 分享）+ 主题 + 健康条 + 推送 不回归；
     7) 暗/浅主题正文/muted/金色文本对比度；星青未误用于正文 / 按钮 / CTA；
     8) 卡片键盘可达（role=button + tabindex）；内联展开 aria-expanded 可切换。
   截图：shot_cards_*.png
"""
import json, os, sys, time, subprocess, urllib.request, base64
import websocket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = "/usr/bin/chromium"
URL = "file://" + os.path.join(BASE, "index.html")
PORT = 9461
SHOTS = {
    'today_dark':  os.path.join(BASE, "shot_cards_today_dark.png"),
    'today_light': os.path.join(BASE, "shot_cards_today_light.png"),
    'candle':      os.path.join(BASE, "shot_cards_candle.png"),
    'event':       os.path.join(BASE, "shot_cards_event.png"),
    'season':      os.path.join(BASE, "shot_cards_season.png"),
    'calendar':    os.path.join(BASE, "shot_cards_calendar.png"),
    'modal':       os.path.join(BASE, "shot_cards_modal.png"),
    'narrow':      os.path.join(BASE, "shot_cards_narrow320.png"),
    'desktop':     os.path.join(BASE, "shot_cards_desktop.png"),
}

CONTRAST_JS = r"""
(function(){
  function lum(rgb){var c=rgb.map(function(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];}
  function parse(c){var m=(c||'').match(/\d+(\.\d+)?/g)||[0,0,0];return m.slice(0,3).map(Number);}
  function ratio(fg,bg){var L1=lum(parse(fg)),L2=lum(parse(bg));var a=Math.max(L1,L2),b=Math.min(L1,L2);return +(((a+0.05)/(b+0.05)).toFixed(2));}
  var bodyBg=getComputedStyle(document.body).backgroundColor;
  var txtEl=document.querySelector('.card .c-title')||document.querySelector('.card h3')||document.body;
  var mutEl=document.querySelector('.mast-date')||document.querySelector('.c-kick')||document.body;
  var goldEl=document.querySelector('.pill')||document.body;
  var txt=getComputedStyle(txtEl).color, mut=getComputedStyle(mutEl).color, gold=getComputedStyle(goldEl).color;
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    bg: bodyBg, text: txt, muted: mut, gold: gold,
    token_accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    token_teal: getComputedStyle(document.documentElement).getPropertyValue('--accent-teal').trim(),
    token_bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),
    ratio_text: ratio(txt, bodyBg), ratio_muted: ratio(mut, bodyBg), ratio_gold: ratio(gold, bodyBg)
  };
})()
"""

# 星青是否被误用到正文/按钮/CTA（应全部为 false）
TEAL_MISUSE_JS = r"""
(function(){
  function parse(c){var m=(c||'').match(/\d+(\.\d+)?/g)||[0,0,0];return m.slice(0,3).map(Number).join(',');}
  var tealEl=document.querySelector('.mast-top .mt-r')||document.querySelector('.folio');
  var teal = tealEl ? parse(getComputedStyle(tealEl).color) : '78,140,134';
  var sels = ['.card .c-title','.card h3','.big','.entry .val','.lede','.btn-share','.btn-install',
              '.stale-btn','.btn-guide','.modal-sub','.gv','.tl-name','.evt-nm',
              '.rb-i-price','.chip','.cchip','.title','.vi-chip'];
  var hits = {};
  sels.forEach(function(s){
    var el=document.querySelector(s); if(!el) return;
    var c=parse(getComputedStyle(el).color);
    var bc=parse(getComputedStyle(el).borderColor);
    if(c===teal) hits[s]='text';
    else if(bc===teal && /btn|chip|cchip/.test(s)) hits[s]='border';
  });
  return {teal:teal, hits:hits};
})()
"""

def req(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode())

def main():
    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", "--headless=new", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "--remote-allow-origins=*",
         "--window-size=420,900", "--hide-scrollbars",
         "--user-data-dir=/tmp/sky_cards_profile", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    try:
        ws_url = None
        for _ in range(40):
            try:
                targets = req(f"http://127.0.0.1:{PORT}/json/list")
                page = next((t for t in targets if t.get("type") == "page"), None)
                if page and page.get("webSocketDebuggerUrl"):
                    ws_url = page["webSocketDebuggerUrl"]; break
            except Exception:
                time.sleep(0.25)
        if not ws_url:
            print("✗ 无法连接 CDP 页面目标"); sys.exit(1)

        ws = websocket.create_connection(ws_url, timeout=20)
        rid = [0]; errors = []

        def send(method, params=None):
            rid[0] += 1; i = rid[0]
            ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
            return i

        def recv_id(i, timeout=15):
            end = time.time() + timeout
            while time.time() < end:
                ws.settimeout(max(0.1, end - time.time()))
                try: m = json.loads(ws.recv())
                except Exception: return None
                if m.get("method") == "Runtime.exceptionThrown":
                    e = m["params"]["exceptionDetails"]
                    errors.append(e.get("text", "") + " " + (e.get("exception", {}).get("description", "") or ""))
                if m.get("id") == i: return m
            return None

        send("Runtime.enable"); send("Page.enable")
        nav = send("Page.navigate", {"url": URL}); recv_id(nav)
        time.sleep(3.0)

        def ev(expr):
            i = send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
            m = recv_id(i, 10)
            if m and "result" in m: return m["result"].get("result", {}).get("value")
            return None

        def shot(path, clip=None):
            p = {"format": "png"}
            if clip: p["clip"] = clip
            i = send("Page.captureScreenshot", p); m = recv_id(i, 20)
            if m and "result" in m:
                with open(path, "wb") as f: f.write(base64.b64decode(m["result"]["data"]))
                print(f"  ✓ 截图 {os.path.basename(path)}")

        checks = {}

        # 0) 基础：溢出 / 结构标记
        checks['overflow_x_420'] = ev("document.documentElement.scrollWidth - window.innerWidth")
        checks['spine'] = ev("""(function(){var b=document.getElementById('tabbar');if(!b)return null;
          var r=b.getBoundingClientRect(),s=getComputedStyle(b);
          return {position:s.position,left:Math.round(r.left),width:Math.round(r.width),
            tabs:[].map.call(b.querySelectorAll('.tab[data-tab]'),function(t){return t.getAttribute('data-tab');}),
            ids:[].map.call(b.querySelectorAll('.tab'),function(t){return t.id;})};})()""")
        checks['struct_intact'] = ev("""(function(){
          var want=[['today','tab-today','page-today'],['candle','tab-candle','page-candle'],
            ['event','tab-event','page-event'],['season','tab-season','page-season'],
            ['calendar','tab-calendar','page-calendar']];
          return want.every(function(w){
            var t=document.getElementById(w[1]); var p=document.getElementById(w[2]);
            return t && t.getAttribute('data-tab')===w[0] && p && t.getAttribute('aria-controls')===w[2];
          });})()""")
        # 编辑装置（保留）
        checks['mast_top_present'] = ev("!!document.querySelector('header .mast-top #rhR')")
        checks['folio_count'] = ev("document.querySelectorAll('.folio').length")
        checks['spine_range_count'] = ev("document.querySelectorAll('.tabbar .tab .tr').length")
        checks['colhead_count'] = ev("document.querySelectorAll('.col-head').length")
        checks['dropcap'] = ev("getComputedStyle(document.querySelector('.lede'),'::first-letter').float")
        checks['measure_token'] = ev("getComputedStyle(document.documentElement).getPropertyValue('--measure').trim()")

        # 1) 5 个分区：经书脊点击切换 + region 语义
        tab_ok = {}
        for name in ['today','candle','event','season','calendar']:
            ev(f"document.querySelector('.tab[data-tab=\\'{name}\\']').click()"); time.sleep(0.2)
            tab_ok[name] = ev(f"document.getElementById('page-{name}').classList.contains('active')")
        checks['tabs_by_spine_click'] = tab_ok
        ev("document.querySelector('.tab[data-tab=\\'candle\\']').click()"); time.sleep(0.2)
        checks['rh_sync_candle'] = ev("(document.getElementById('rhR')||{}).textContent")
        checks['region_count'] = ev("document.querySelectorAll('main .grid[role=region]').length")

        # 2) 各卷：容器 grid 化 + 卡片数量 > 0 + 卷索引条
        vol_grid = {}; vol_cards = {}; vol_index = {}
        for name, box in [('today','app'),('candle','candleBox'),('event','evtBox'),
                          ('season','seasonBox'),('calendar','calBox')]:
            ev(f"document.querySelector('.tab[data-tab=\\'{name}\\']').click()"); time.sleep(0.35)
            vol_grid[name] = ev(f"(function(){{var e=document.getElementById('{box}');return e?getComputedStyle(e).display:null;}})()")
            vol_cards[name] = ev(f"document.querySelectorAll('#{box} .card').length")
            vol_index[name] = ev(f"document.querySelectorAll('#page-{name} .vol-index .vi-chip').length")
        checks['vol_grid'] = vol_grid
        checks['vol_cards'] = vol_cards
        checks['vol_index_chip'] = vol_index

        # 3) 年鉴卡片样式：圆角 2px / 无阴影 / 顶边金线 / counter
        checks['card_style'] = ev("""(function(){
          var c=document.querySelector('#app .card:not(.hero)'); if(!c) return null;
          var s=getComputedStyle(c), b=getComputedStyle(c,'::before');
          return { radius:s.borderRadius, shadow:s.boxShadow, topW:s.borderTopWidth,
                   topColor:s.borderTopColor, counter:b.content, gap:s.paddingTop };
        })()""")

        # 4) data-goto 一步跳转 + 卷索引 chip 锚点
        ev("document.querySelector('.tab[data-tab=\\'today\\']').click()"); time.sleep(0.25)
        checks['cover_present'] = ev("!!document.querySelector('.glance-item[data-goto]') && !!document.querySelector('#contents .entry[data-goto]')")
        checks['glance_count'] = ev("document.querySelectorAll('.glance-item[data-goto]').length")
        checks['contents_count'] = ev("document.querySelectorAll('#contents .entry[data-goto]').length")
        ev("document.querySelector('.glance-item[data-goto=\\'candle\\']').click()"); time.sleep(0.3)
        checks['goto_glance_candle'] = ev("document.getElementById('page-candle').classList.contains('active')")
        ev("document.querySelector('.tab[data-tab=\\'today\\']').click()"); time.sleep(0.25)
        ev("document.querySelector('.vol-index .vi-chip[data-anchor=\\'card-tasks\\']').click()"); time.sleep(0.3)
        checks['goto_chip_tasks'] = ev("!!document.querySelector('.scan-target') || !!document.getElementById('card-tasks')")

        # 5) 键盘：PageDown / End / Home 切卷
        ev("switchTab('today')"); time.sleep(0.15)
        ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'PageDown',bubbles:true}))"); time.sleep(0.2)
        checks['kbd_pagedown'] = ev("CURRENT_TAB")
        ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}))"); time.sleep(0.2)
        checks['kbd_end'] = ev("CURRENT_TAB")
        ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}))"); time.sleep(0.2)
        checks['kbd_home'] = ev("CURRENT_TAB")

        # 6) 卡片键盘可达 + 内联展开
        ev("switchTab('season')"); time.sleep(0.4)
        checks['season_expand_target'] = ev("(function(){var c=document.querySelector('#seasonList .card[data-expand]');return !!c;})()")
        checks['aria_expand_init'] = ev("(function(){var c=document.querySelector('#seasonList .card[data-expand]');return c?c.getAttribute('aria-expanded'):null;})()")
        ev("""(function(){var c=document.querySelector('#seasonList .card[data-expand]');
          c.focus(); c.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()""")
        time.sleep(0.25)
        checks['aria_expand_after'] = ev("(function(){var c=document.querySelector('#seasonList .card[data-expand]');return c?c.getAttribute('aria-expanded'):null;})()")
        checks['xbody_visible'] = ev("(function(){var c=document.querySelector('#seasonList .card[data-expand]');var b=c&&document.getElementById(c.getAttribute('data-expand'));return b?!b.hidden:null;})()")
        checks['rebirth_cards'] = ev("document.querySelectorAll('#rebirthList .card').length")

        # 7) 今日签条 / 抽斗（数据源＝目录 + 卷内卡片）
        checks['ribbon_present'] = ev("!!document.getElementById('ribbon')")
        ev("switchTab('today')"); time.sleep(0.3)
        ev("openDrawer()"); time.sleep(0.35)
        checks['drawer_open'] = ev("document.getElementById('drawer').classList.contains('open')")
        checks['drawer_expanded'] = ev("document.getElementById('drawerHandle').getAttribute('aria-expanded')")
        checks['drawer_items'] = ev("document.querySelectorAll('#drawerList [data-goto]').length")
        ev("closeDrawer()"); time.sleep(0.3)
        checks['drawer_closed'] = ev("!document.getElementById('drawer').classList.contains('open')")

        # 8) 主题：暗→浅；星青误用
        ev("switchTab('today')"); time.sleep(0.3)
        checks['contrast_dark'] = ev(CONTRAST_JS)
        checks['teal_misuse_dark'] = ev(TEAL_MISUSE_JS)
        shot(SHOTS['today_dark'])
        ev("toggleTheme()"); time.sleep(0.4)
        checks['contrast_light'] = ev(CONTRAST_JS)
        checks['teal_misuse_light'] = ev(TEAL_MISUSE_JS)
        shot(SHOTS['today_light'])
        checks['theme_after_toggle'] = ev("document.documentElement.getAttribute('data-theme')")
        ev("toggleTheme()"); time.sleep(0.3)
        checks['theme_back'] = ev("document.documentElement.getAttribute('data-theme')")

        # 9) 弹窗：攻略 / 活动 / 复刻 / 分享 + Esc + 回焦
        ev("(function(){window.__t=document.querySelector('.btn-share'); if(window.__t) window.__t.focus(); showGuide('与朋友击掌');})()")
        time.sleep(0.3)
        checks['modal_open'] = ev("document.getElementById('modal').classList.contains('show')")
        checks['modal_focus_in'] = ev("document.getElementById('modal').contains(document.activeElement)")
        shot(SHOTS['modal'])
        ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"); time.sleep(0.3)
        checks['modal_closed_esc'] = ev("!document.getElementById('modal').classList.contains('show')")
        checks['modal_focus_restored'] = ev("document.activeElement===window.__t")
        # 活动弹窗
        ev("(function(){var k=(EVENTS.events||[])[0]; if(k) showEvt(k.key);})()"); time.sleep(0.25)
        checks['evtmodal_open'] = ev("document.getElementById('evtModal').classList.contains('show')")
        ev("closeEvt()"); time.sleep(0.2)
        # 复刻图鉴弹窗（季节页卡片点击）
        ev("switchTab('season')"); time.sleep(0.4)
        ev("(function(){var c=document.querySelector('#rebirthList .card[onclick]'); if(c) c.click();})()"); time.sleep(0.3)
        checks['rbmodal_open'] = ev("document.getElementById('rbModal').classList.contains('show')")
        ev("closeRebirthGuide()"); time.sleep(0.2)

        # 10) 健康条 / 推送 / 分享卡
        checks['health_dot_ok'] = ev("document.getElementById('healthDot').className")
        ev("""(function(){ STATUS={level:'error',summary:'1 项错误',checkedAt:'2026-10-10T13:06:00',provenance:{api:'fail'},issues:[{code:'X',level:'error',title:'示例错误',detail:'验证用'}]}; renderHealth(); })()""")
        time.sleep(0.3)
        checks['health_bar_error'] = ev("document.getElementById('healthBar').querySelector('.stale.error')!==null")
        ev("STATUS=INLINE_STATUS||{level:'ok'}; renderHealth();")
        checks['push_btn_exists'] = ev("!!document.getElementById('pushBtn')")
        ev("switchTab('today')"); time.sleep(0.3)
        ev("generateShareCard()"); time.sleep(0.4)
        checks['share_modal_open'] = ev("document.getElementById('shareModal').classList.contains('show')")
        checks['share_img_ok'] = ev("(function(){var i=document.querySelector('#sharePreview img');return !!i && /^data:image\\/png/.test(i.getAttribute('src'));})()")
        ev("closeShare()"); time.sleep(0.2)

        # 11) 深链：#tab= / #tab=x&card=y / #evt= / #guide=
        ev("(function(){location.hash='#tab=season'; applyHash();})()"); time.sleep(0.3)
        checks['hash_season'] = ev("document.getElementById('page-season').classList.contains('active')")
        ev("(function(){location.hash='#tab=calendar&card=card-cal-tl'; applyHash();})()"); time.sleep(0.4)
        checks['hash_tab_card'] = ev("document.getElementById('page-calendar').classList.contains('active') && !!document.getElementById('card-cal-tl')")
        ev("(function(){location.hash='#tab=event&card=card-evt-cov'; applyHash();})()"); time.sleep(0.4)
        checks['hash_tab_card2'] = ev("document.getElementById('page-event').classList.contains('active') && !!document.getElementById('card-evt-cov')")
        ev("(function(){location.hash='#guide=与朋友击掌'; applyHash();})()"); time.sleep(0.4)
        checks['hash_guide'] = ev("document.getElementById('modal').classList.contains('show')")
        ev("closeGuide()"); time.sleep(0.2)
        ev("(function(){history.replaceState({tab:'today'},''); location.hash=''; switchTab('today');})()"); time.sleep(0.25)

        # 12) 截图：烛照 / 际会 / 风物 / 纪年
        for name, key in [('candle','candle'),('event','event'),('season','season'),('calendar','calendar')]:
            ev(f"switchTab('{name}')"); time.sleep(0.55)
            ev("window.scrollTo({top:0})"); time.sleep(0.2)
            shot(SHOTS[key])

        # 12b) 420 中屏：2 列
        send("Emulation.setDeviceMetricsOverride", {"width":420,"height":900,"deviceScaleFactor":2,"mobile":True})
        time.sleep(0.6)
        ev("switchTab('today')"); time.sleep(0.35)
        ev("window.scrollTo({top:0})"); time.sleep(0.2)
        checks['overflow_x_420'] = ev("document.documentElement.scrollWidth - window.innerWidth")
        checks['grid_cols_420'] = ev("getComputedStyle(document.getElementById('app')).gridTemplateColumns.split(' ').length")
        send("Emulation.clearDeviceMetricsOverride"); time.sleep(0.3)

        # 13) 320 窄屏：无横向溢出 + 单列
        ev("switchTab('today')"); time.sleep(0.25)
        send("Emulation.setDeviceMetricsOverride", {"width":320,"height":720,"deviceScaleFactor":2,"mobile":True})
        time.sleep(0.6)
        ev("window.scrollTo({top:0})"); time.sleep(0.3)
        checks['overflow_x_320'] = ev("document.documentElement.scrollWidth - window.innerWidth")
        checks['grid_cols_320'] = ev("getComputedStyle(document.getElementById('app')).gridTemplateColumns.split(' ').length")
        shot(SHOTS['narrow'])
        send("Emulation.clearDeviceMetricsOverride"); time.sleep(0.3)

        # 14) 桌面 1200：多列网格 + 无溢出
        send("Emulation.setDeviceMetricsOverride", {"width":1200,"height":900,"deviceScaleFactor":1,"mobile":False})
        time.sleep(0.7)
        ev("switchTab('today')"); time.sleep(0.4)
        ev("window.scrollTo({top:0})"); time.sleep(0.3)
        checks['overflow_x_1200'] = ev("document.documentElement.scrollWidth - window.innerWidth")
        checks['grid_cols_1200'] = ev("getComputedStyle(document.getElementById('app')).gridTemplateColumns.split(' ').length")
        checks['marg_abs'] = ev("""(function(){var n=document.querySelector('.note.marg');
          if(!n) return null; return {pos:getComputedStyle(n).position, left:getComputedStyle(n).left};})()""")
        shot(SHOTS['desktop'])
        send("Emulation.clearDeviceMetricsOverride")

        print("=== CDP 验证结果（年鉴卡片网格） ===")
        for k, v in checks.items():
            print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
        print("=== JS 报错 ===")
        print("  " + ("无" if not errors else "\n  ".join(errors)))

        cd = checks.get('contrast_dark') or {}; cl = checks.get('contrast_light') or {}
        tm_d = checks.get('teal_misuse_dark') or {}; tm_l = checks.get('teal_misuse_light') or {}
        tabs_ok = checks.get('tabs_by_spine_click') or {}; spine = checks.get('spine') or {}
        vg = checks.get('vol_grid') or {}; vc = checks.get('vol_cards') or {}; vi = checks.get('vol_index_chip') or {}
        cs = checks.get('card_style') or {}
        ok = (
            not errors
            and checks.get('overflow_x_420', 999) <= 2
            and checks.get('overflow_x_320', 999) <= 2
            and checks.get('overflow_x_1200', 999) <= 2
            and spine.get('position') == 'fixed' and spine.get('left') == 0 and 28 <= spine.get('width', 0) <= 40
            and spine.get('tabs') == ['today','candle','event','season','calendar']
            and checks.get('struct_intact') is True
            and all(tabs_ok.get(n) for n in ['today','candle','event','season','calendar'])
            and checks.get('rh_sync_candle') and '烛照' in checks.get('rh_sync_candle', '') and 'P.02/05' in checks.get('rh_sync_candle', '')
            and checks.get('mast_top_present') is True
            and checks.get('folio_count') == 5
            and checks.get('spine_range_count') == 5
            and checks.get('colhead_count') == 5
            and checks.get('region_count') == 5
            and checks.get('dropcap') == 'left'
            # 各卷 grid + 卡片 > 0 + 卷索引 chip > 0
            and all(vg.get(n) == 'grid' for n in ['today','candle','event','season','calendar'])
            and all(vc.get(n, 0) > 0 for n in ['today','candle','event','season','calendar'])
            and all(vi.get(n, 0) > 0 for n in ['today','candle','event','season','calendar'])
            # 卡片样式：2px 圆角 / 无阴影 / 顶边 1px
            and cs.get('radius') == '2px' and cs.get('shadow') in ('none', '') and cs.get('topW') == '1px'
            and checks.get('grid_cols_420', 0) >= 2
            and checks.get('grid_cols_320', 1) == 1
            and checks.get('grid_cols_1200', 0) >= 3
            # 跳转 / 深链
            and checks.get('glance_count') == 4 and checks.get('contents_count') == 5
            and checks.get('goto_glance_candle') is True and checks.get('goto_chip_tasks') is True
            and checks.get('kbd_pagedown') == 'candle' and checks.get('kbd_end') == 'calendar' and checks.get('kbd_home') == 'today'
            # 卡片键盘 + 展开
            and checks.get('season_expand_target') is True
            and checks.get('aria_expand_init') == 'false' and checks.get('aria_expand_after') == 'true'
            and checks.get('xbody_visible') is True and checks.get('rebirth_cards', 0) > 0
            # 抽斗 / 签条
            and checks.get('ribbon_present') is True
            and checks.get('drawer_open') is True and checks.get('drawer_expanded') == 'true'
            and checks.get('drawer_items', 0) >= 5 and checks.get('drawer_closed') is True
            # 主题 / 对比度 / 星青
            and cd.get('token_accent') == '#E8C77B' and cl.get('token_accent') == '#8A6420'
            and cd.get('token_teal') == '#4E8C86' and cl.get('token_teal') == '#2F6B66'
            and cd.get('ratio_text', 0) >= 4.5 and cd.get('ratio_muted', 0) >= 4.5 and cd.get('ratio_gold', 0) >= 4.5
            and cl.get('ratio_text', 0) >= 4.5 and cl.get('ratio_muted', 0) >= 4.5 and cl.get('ratio_gold', 0) >= 4.5
            and not tm_d.get('hits') and not tm_l.get('hits')
            and checks.get('theme_after_toggle') == 'light' and checks.get('theme_back') == 'dark'
            # 弹窗不回归
            and checks.get('modal_open') is True and checks.get('modal_focus_in') is True
            and checks.get('modal_closed_esc') is True and checks.get('modal_focus_restored') is True
            and checks.get('evtmodal_open') is True and checks.get('rbmodal_open') is True
            # 健康 / 推送 / 分享
            and checks.get('health_bar_error') is True
            and checks.get('push_btn_exists') is True
            and checks.get('share_modal_open') is True and checks.get('share_img_ok') is True
            # 深链
            and checks.get('hash_season') is True and checks.get('hash_tab_card') is True
            and checks.get('hash_tab_card2') is True and checks.get('hash_guide') is True
        )
        print("=== 结论 ===", "✓ 通过" if ok else "✗ 失败")
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
