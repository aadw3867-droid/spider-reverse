"""小红书 x-s 相关的密码学原语（纯 Python，无第三方依赖）。

- md5(x)                    : x5 / u / p
- 自定义 base64（换表）      : XYS_ 外层编码
- x6 / x7 组装              : 基于 webSsk + 4 字节随机 nonce 的 SHA1
"""

from __future__ import annotations

import base64
import hashlib
import os


class XhsCrypto:
    """x-s 参数用到的哈希 / 编码。"""

    APP_ID = "xhs-pc-web"
    VERSION = "4.4.3"

    STD_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    CUSTOM_ALPHABET = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"

    @staticmethod
    def md5_hex(text: str) -> str:
        """对 UTF-8 文本做 md5，返回 32 位小写 hex。"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @classmethod
    def custom_base64(cls, raw: bytes) -> str:
        """标准 base64 后按字母表换表。"""
        std = base64.b64encode(raw).decode("ascii")
        return "".join(cls.CUSTOM_ALPHABET[cls.STD_ALPHABET.index(ch)]
                       if ch in cls.STD_ALPHABET else ch for ch in std)

    @classmethod
    def build_x6_x7(cls, web_ssk_b64: str, u_hex: str, nonce: bytes | None = None):
        """生成 (x6, x7)。

        S   = nonce(4B) + sha1(web_ssk_bytes + nonce)      # 24 字节
        x7  = base64(S)
        x6  = base64(sha1(u_hex_bytes + S))
        """
        nonce = nonce or os.urandom(4)
        ssk = base64.b64decode(web_ssk_b64)
        s = nonce + hashlib.sha1(ssk + nonce).digest()
        x7 = base64.b64encode(s).decode("ascii")
        x6 = base64.b64encode(hashlib.sha1(bytes.fromhex(u_hex) + s).digest()).decode("ascii")
        return x6, x7
