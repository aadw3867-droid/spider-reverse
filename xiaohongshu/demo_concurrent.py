"""并发示例：签名吞吐 + 并发真实请求（默认打印完整响应体）。

用法（在 xbs/小红书 目录下）：

  python demo_concurrent.py                          # 默认 --sign 100 --req 8 --workers 8
  python demo_concurrent.py --sign 2000 --req 32 --workers 16
  python demo_concurrent.py --req 0                  # 只测签名吞吐（不发网络）
  python demo_concurrent.py --homefeed --req 8       # 并发打 homefeed（更严风控，可能被限）
  python demo_concurrent.py --save out.json          # 把所有响应原文存文件

说明：
- 签名是纯算，内部走常驻 Node worker 池，无状态、线程安全；
- requests.Session 非线程安全，所以每个线程各自一个 XhsClient（线程局部）。
"""

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from xhs import XhsClient


ME_API = "/api/sns/web/v2/user/me"
FEED_API = "/api/sns/web/v1/homefeed"
FEED_BODY = {
    "cursor_score": "", "num": 20, "refresh_type": 3, "note_index": 6,
    "unread_begin_note_id": "", "unread_end_note_id": "", "unread_note_count": 0,
    "category": "homefeed_recommend", "search_key": "", "need_num": 8,
    "image_formats": ["jpg", "webp", "avif"], "need_filter_image": False,
}


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "config.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def bench_sign(cfg: dict, n: int, workers: int) -> None:
    signer = XhsClient(cfg).signer

    def work(_):
        return signer.sign(ME_API, "")["x3"]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        xs = list(ex.map(work, range(n)))
    dt = time.time() - t0
    ok = sum(1 for x in xs if isinstance(x, str) and x.startswith("mns") and len(x) == 200)
    print(f"[sign] {n} 次 / {workers} 线程 : {dt:.2f}s  {n / dt:.1f} 次/秒  有效 x3 {ok}/{n}")


def bench_requests(cfg: dict, n: int, workers: int, homefeed: bool, save_path: str) -> None:
    local = threading.local()

    def get_client() -> XhsClient:
        if not hasattr(local, "client"):
            local.client = XhsClient(cfg)
        return local.client

    def work(i):
        client = get_client()
        t0 = time.time()
        try:
            resp = client.post(FEED_API, FEED_BODY) if homefeed else client.get(ME_API)
            dt = time.time() - t0
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = {"_raw": resp.text[:500]}
            return {"i": i, "status": resp.status_code, "code": body.get("code"), "body": body, "dt": dt}
        except Exception as exc:  # noqa: BLE001
            return {"i": i, "status": "ERR", "code": None, "body": {"error": str(exc)}, "dt": time.time() - t0}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(work, range(n)))
    dt = time.time() - t0

    ok = sum(1 for r in results if r["status"] == 200 and r["code"] == 0)
    status = {}
    for r in results:
        status[r["status"]] = status.get(r["status"], 0) + 1
    lat = sorted(r["dt"] for r in results)
    p50 = lat[len(lat) // 2] * 1000 if lat else 0
    api = "homefeed" if homefeed else "user/me"
    print(f"[req]  {api} {n} 次 / {workers} 线程 : {dt:.2f}s  {n / dt:.1f} 次/秒  "
          f"成功 {ok}/{n}  状态 {status}  P50 {p50:.0f}ms")

    for r in results[:min(5, n)]:
        data = r["body"].get("data") or {}
        if homefeed:
            extra = f"items={len(data.get('items') or [])}"
        else:
            extra = f"guest={data.get('guest')} user_id={data.get('user_id')}"
        print(f"  - #{r['i']} HTTP {r['status']} code={r['code']} {extra}")

    # 默认打印一条完整响应体
    sample = results[0]["body"]
    text = json.dumps(sample, ensure_ascii=False, indent=2)
    print("\n完整响应样例 (#0):")
    print(text if len(text) <= 4000 else text[:4000] + "\n  ...(已截断，完整内容用 --save 存文件)")
    if homefeed:
        for item in ((sample.get("data") or {}).get("items") or [])[:5]:
            card = item.get("note_card") or {}
            print("   *", card.get("display_title") or item.get("id"))

    if save_path:
        with open(save_path, "w", encoding="utf-8") as fh:
            json.dump([r["body"] for r in results], fh, ensure_ascii=False, indent=2)
        print(f"\n已保存 {n} 条完整响应 -> {save_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sign", type=int, default=100, help="签名基准次数（0 跳过）")
    parser.add_argument("--req", type=int, default=8, help="真实请求次数（0 跳过）")
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--homefeed", action="store_true", help="并发请求 homefeed 而非 user/me")
    parser.add_argument("--save", default="", help="把所有响应原文保存到该 JSON 文件")
    parser.add_argument("--full", action="store_true", help="（兼容旧参数，现已默认打印完整响应）")
    args = parser.parse_args()

    cfg = load_config()
    print(f"workers={args.workers}  sign={args.sign}  req={args.req}  "
          f"api={'homefeed' if args.homefeed else 'user/me'}")
    if args.sign > 0:
        bench_sign(cfg, args.sign, args.workers)
    if args.req > 0:
        bench_requests(cfg, args.req, args.workers, args.homefeed, args.save)


if __name__ == "__main__":
    main()
