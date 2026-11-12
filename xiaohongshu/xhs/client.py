"""带自动签名的小红书请求客户端。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from .mns import MnsVM
from .signer import XhsSigner


DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")


class XhsClient:
    def __init__(self, config: Dict[str, Any], session: Optional[requests.Session] = None,
                 base_url: str = "https://edith.xiaohongshu.com") -> None:
        self.config = dict(config)
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        config.setdefault("ua", DEFAULT_UA)
        self.signer = XhsSigner(MnsVM(), config)

    # -- cookie 管理 --
    @property
    def cookie(self) -> str:
        return self.signer.cookie

    def set_cookie(self, cookie) -> None:
        self.signer.update(cookie=cookie)

    # -- 请求 --
    def _common_headers(self) -> Dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "origin": "https://www.xiaohongshu.com",
            "referer": "https://www.xiaohongshu.com/",
            "user-agent": self.signer.ua or DEFAULT_UA,
        }
        if self.signer.cookie:
            headers["cookie"] = self.signer.cookie
        return headers

    def post(self, api_path: str, body: Dict[str, Any], timeout: int = 20) -> requests.Response:
        body_str = json.dumps(body or {}, ensure_ascii=False, separators=(",", ":"))
        headers = self._common_headers()
        headers.update(self.signer.headers(api_path, body))
        return self.session.post(self.base_url + api_path, data=body_str.encode("utf-8"),
                                 headers=headers, timeout=timeout)

    def get(self, api_path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> requests.Response:
        query = urlencode(params or {})
        sign_body = ("?" + query) if query else ""
        headers = self._common_headers()
        headers.update(self.signer.headers(api_path, sign_body))
        url = self.base_url + api_path + (("?" + query) if query else "")
        return self.session.get(url, headers=headers, timeout=timeout)
