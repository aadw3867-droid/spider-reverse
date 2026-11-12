"""x-s / x-t / x-s-common 组装。

x-s = "XYS_" + 自定义base64(JSON{x0..x7})
    x0 = 版本 4.4.3
    x1 = appId xhs-pc-web
    x2 = 平台 "Windows"
    x3 = mnsv2(api+body, md5(api+body), md5(api))   # 由 MnsVM 产出
    x4 = "object"
    x5 = md5(api+body)
    x6 = {appId: sha1(u_bytes + S)}
    x7 = {appId: base64(S)}
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .crypto import XhsCrypto
from .mns import MnsVM


class XhsSigner:
    def __init__(self, mns: MnsVM, config: Dict[str, Any]) -> None:
        self.mns = mns
        self.app_id = config.get("appId") or XhsCrypto.APP_ID
        self.version = config.get("version") or XhsCrypto.VERSION
        self.bc = config.get("bc") or ""
        self.cookie = config.get("cookie") or ""
        self.web_ssk = config.get("webSsk") or ""
        self.xs_common = config.get("xsCommon") or ""
        self.storage = config.get("storage") or None
        self.ua = config.get("ua") or None

    def update(self, **kwargs: Any) -> None:
        """热更新 cookie / bc / webSsk / xsCommon 等。"""
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "cookie" and isinstance(value, dict):
                value = "; ".join(f"{k}={v}" for k, v in value.items())
            setattr(self, key, value)

    def sign(self, api_path: str, body: Any) -> Dict[str, Any]:
        body_str = body if isinstance(body, str) else json.dumps(body or {}, ensure_ascii=False, separators=(",", ":"))
        c = api_path + body_str
        u = XhsCrypto.md5_hex(c)
        p = XhsCrypto.md5_hex(api_path)

        x3 = self.mns.sign(c, u, p, bc=self.bc, cookie=self.cookie,
                           web_ssk=self.web_ssk, storage=self.storage,
                           app_id=self.app_id, ua=self.ua)
        x6, x7 = XhsCrypto.build_x6_x7(self.web_ssk, u)

        payload = {
            "x0": self.version, "x1": self.app_id, "x2": "Windows", "x3": x3, "x4": "object",
            "x5": u,
            "x6": {self.app_id: x6},
            "x7": {self.app_id: x7},
        }
        xs = "XYS_" + XhsCrypto.custom_base64(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return {
            "payload": payload,
            "x3": x3,
            "xs": xs,
            "xt": str(__import__("time").time_ns() // 1_000_000),
            "xs_common": self.xs_common,
            "body_str": body_str,
            "api_path": api_path,
        }

    def headers(self, api_path: str, body: Any, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        signed = self.sign(api_path, body)
        headers = {
            "content-type": "application/json;charset=UTF-8",
            "x-s": signed["xs"],
            "x-t": signed["xt"],
            "x-s-common": signed["xs_common"],
        }
        if extra:
            headers.update(extra)
        return headers
