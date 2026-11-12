"""更新账号会话：写入 config.json 的 cookie / webSsk，并自检 user/me 与 homefeed。

用法（A：从文件读，最省事）：
    在 assets/session.txt 里写两行——
        第 1 行 = 完整 Cookie（从 Network 请求头复制，含 web_session）
        第 2 行 = webSsk
    python set_session.py

用法（B：命令行直接传）：
    python set_session.py --cookie "a1=...; web_session=..." --webssk "xxxx"

注意：web_session 是 httpOnly，document.cookie 里没有，必须从请求头取。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "assets", "config.json")
SESSION_TXT = os.path.join(BASE, "assets", "session.txt")


def _normalize_webssk(raw: str) -> str:
    raw = (raw or "").strip().strip('"')
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return str(obj.get("xhs-pc-web") or next(iter(obj.values()), ""))
        except Exception:  # noqa: BLE001
            pass
    return raw


def _read_session_file() -> tuple[str, str]:
    with open(SESSION_TXT, "r", encoding="utf-8-sig") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    if len(lines) < 2:
        raise SystemExit(f"{SESSION_TXT} 需要两行：第1行 Cookie，第2行 webSsk")
    return lines[0], lines[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie", default="")
    ap.add_argument("--webssk", default="")
    ap.add_argument("--no-check", action="store_true", help="只写配置，不做联网自检")
    args = ap.parse_args()

    if args.cookie:
        cookie, webssk = args.cookie.strip(), args.webssk.strip()
    else:
        cookie, webssk = _read_session_file()
    webssk = _normalize_webssk(webssk)

    if "web_session=" not in cookie:
        print("!! 警告：cookie 里没有 web_session，登录态可能无效")

    with open(CFG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["cookie"] = cookie
    cfg["webSsk"] = webssk
    with open(CFG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    print(f"已写入 config.json : cookie {len(cookie)}B, webSsk {len(webssk)}B")

    if args.no_check:
        return

    sys.path.insert(0, BASE)
    from xhs import XhsClient  # noqa: E402

    client = XhsClient(cfg)
    r = client.get("/api/sns/web/v2/user/me")
    print("user/me ->", r.status_code, r.text[:200])

    body = {
        "cursor_score": "", "num": 20, "refresh_type": 3, "note_index": 6,
        "unread_begin_note_id": "", "unread_end_note_id": "", "unread_note_count": 0,
        "category": "homefeed_recommend", "search_key": "", "need_num": 8,
        "image_formats": ["jpg", "webp", "avif"], "need_filter_image": False,
    }
    r2 = client.post("/api/sns/web/v1/homefeed", body)
    try:
        j = r2.json()
    except Exception:  # noqa: BLE001
        j = {}
    items = (j.get("data") or {}).get("items") or []
    print(f"homefeed -> {r2.status_code} code={j.get('code')} items={len(items)}")
    for it in items[:5]:
        card = it.get("note_card") or {}
        print("   *", card.get("display_title") or it.get("id"))


if __name__ == "__main__":
    main()
