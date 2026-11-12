"""示例：用纯算 x-s 请求小红书接口。

- /api/sns/web/v2/user/me  : GET，连通性自检
- /api/sns/web/v1/homefeed : POST，首页 feed

用前确认 assets/config.json 的 cookie（含 httpOnly web_session）仍有效。
"""

import json
import os

from xhs import XhsClient


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "config.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


FEED_API = "/api/sns/web/v1/homefeed"
FEED_BODY = {
    "cursor_score": "",
    "num": 20,
    "refresh_type": 3,
    "note_index": 6,
    "unread_begin_note_id": "",
    "unread_end_note_id": "",
    "unread_note_count": 0,
    "category": "homefeed_recommend",
    "search_key": "",
    "need_num": 8,
    "image_formats": ["jpg", "webp", "avif"],
    "need_filter_image": False,
}


def main() -> None:
    client = XhsClient(load_config())

    # 1) GET 自检
    me = client.get("/api/sns/web/v2/user/me")
    mj = me.json()
    print("[user/me]", "HTTP", me.status_code,
          "| code =", mj.get("code"), "| msg =", mj.get("msg"),
          "| guest =", (mj.get("data") or {}).get("guest"))
    print("  data =", json.dumps(mj.get("data"), ensure_ascii=False))

    # 2) POST 首页 feed
    signed = client.signer.sign(FEED_API, FEED_BODY)
    print("[sign] x3 =", signed["x3"][:24], f"(len={len(signed['x3'])})  x-s len={len(signed['xs'])}")
    resp = client.post(FEED_API, FEED_BODY)
    fj = resp.json()
    items = (fj.get("data") or {}).get("items") or []
    print("[homefeed]", "HTTP", resp.status_code,
          "| code =", fj.get("code"), "| msg =", fj.get("msg"),
          "| items =", len(items),
          "| cursor =", (fj.get("data") or {}).get("cursor_score"))
    for item in items[:5]:
        card = item.get("note_card") or {}
        print("  -", card.get("display_title") or item.get("id"))


if __name__ == "__main__":
    main()
