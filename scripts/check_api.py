#!/usr/bin/env python3.11
"""
API 自检 —— 填完 key 后先跑这个

    python3.11 scripts/check_api.py           看每一项能不能通、拿到多少条
    python3.11 scripts/check_api.py --dump    打印每个端点原始 JSON（排错用）
    python3.11 scripts/check_api.py --dry     只查不写，不改动 data.json
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sky_api  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if "--dump" in sys.argv:
        print("========== 原始返回 ==========")
        print("----- 文本端点（JSON）-----")
        for ep, path in sky_api.ENDPOINTS.items():
            p, j, err = sky_api.try_all(ep)
            print(f"\n----- {ep}  ({path})  服务商={p or '×'}  err={err}")
            if j is not None:
                print(json.dumps(j, ensure_ascii=False)[:1200])
        print("\n----- 图片端点（JPEG 二进制，只报大小）-----")
        key = sky_api.load_key()
        for ep, fname in sky_api.IMAGE_ENDPOINTS.items():
            try:
                ctype, body = sky_api.fetch_image_bytes(ep, key)
                print(f"  {ep}: {len(body)} 字节  {ctype}  ext={sky_api._ext_of(body)}")
            except Exception as e:
                print(f"  {ep}: 下载失败 {e}")
        return 0

    key = sky_api.load_key()
    print("=" * 62)
    print("光遇第三方 API 自检")
    print("=" * 62)
    if not key:
        print("✗ 没读到 KEY。")
        print("  1) 去 https://api.t1qq.com 注册（免费）")
        print("  2) 到 https://api.t1qq.com/user/key 复制 KEY")
        print("  3) 回来跑： bash scripts/set_api_key.sh 你的KEY")
        return 1
    print(f"✓ KEY 已配置（{key[:6]}…{key[-4:]}，共 {len(key)} 位）\n")

    got = sky_api.fetch_all()
    if not got.get("ok"):
        print("✗ 全部失败：", got.get("err"))
        return 1

    print("\n---------- 解析结果 ----------")
    for k in ("tasks", "candle", "candleImages", "magic", "stone", "countdown"):
        v = got.get(k)
        if not v:
            continue
        print(f"  {k}:")
        for x in v[:6]:
            print("     ·", x)
    # 图片端点：单独下载看能否拿到
    imgs = sky_api.download_api_images(key, ROOT, verbose=True) if key else {}
    if imgs:
        print("\n  图片端点（已下载到本地）:")
        for ep, rel in imgs.items():
            print(f"     · {ep} -> {rel}")
    print(f"\n  命中服务商: {sorted(set(got['source'].values())) or '（无）'}")

    if "--dry" in sys.argv:
        print("\n--dry：未写入 data.json")
        return 0

    data_path = os.path.join(ROOT, "data.json")
    data = json.load(open(data_path, encoding="utf-8"))
    changed = sky_api.apply_to_data(data, got)
    if not changed:
        print("\n⚠ 没有可用数据写入 —— 跑 --dump 看看返回的字段名，我需要据此调解析")
        return 1
    data["meta"]["updatedAt"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    data["meta"]["updatedTs"] = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(data, open(data_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n✓ 已写入 data.json：{('、'.join(changed))}")
    print("  接下来重建页面内联数据： python3.11 scripts/build_inline.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
