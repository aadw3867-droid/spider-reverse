# -*- coding: utf-8 -*-
"""
main.py — 抖音主页视频列表爬取（Python 发包侧）

分工：
  - Node（sign.js + env.js）: 传统补环境生成 a_bogus 和 x-secsdk-web-signature
  - Python（本文件）: 组装参数、调用 Node 签名、用 curl_cffi 发真实请求

使用前请先在下方 CONFIG 里填入真实会话状态（来自一次授权的浏览器会话）：
  - UIFID      : 设备标识（浏览器 cookie UIFID）
  - s_v_web_id : verify 指纹（浏览器 cookie s_v_web_id）
  - ttwid      : 浏览器 cookie ttwid
  - odin_tt    : 浏览器 cookie odin_tt
  - msToken    : localStorage 里的 xmst（会过期，过期后需刷新）

刷新 msToken（xmst）的参考端点：
  https://mssdk.bytedance.com/web/r/token?ms_appid=6383&msToken=<旧 msToken>
"""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests as cffi_requests

# ---------------------------------------------------------------------------
# 配置区
# ---------------------------------------------------------------------------
SEC_USER_ID = "MS4wLjABAAAAompXkPoYOGsA152dqYoytKycjIZ_aCCxHwGmLX5IsDM"

API_URL = "https://www.douyin.com/aweme/v1/web/aweme/post/"
PAGE_URL = f"https://www.douyin.com/user/{SEC_USER_ID}"

# 签名环境里的 UA 必须与发包 UA 完全一致，否则可能返回 200 但 body 为空
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

# 会话状态（需要你从浏览器里抓取真实值填入）
CONFIG = {
    "cookies": {
        "UIFID": "209b86ca33829c7d9c7b7c40c5eb89f829cca190227d7391efa903940cb34a3ceb695c31c48551aceda14eee998cbfebde3481d58f33ec2715f7413dd5d888cc1d679c3ece573fe994b80def37513d3819255a1e02dbfdb628e8c316c201e173e0b55add0efc4945e1c4a37fee44b648",  # 必填
        "s_v_web_id": "verify_mv6u78em_yBcmdsKM_Gah2_4Xa5_9IqO_zieqk1bpInuO",  # 必填
        "ttwid": "1%7Ch7LuvV8VLYynfUlOc-wNZlnJZ3JbZ7GwFNJky26QJso%7C1791905387%7Ccbfb6e26171e0ad4a22b65e57482bf73fbb3deb1836c9a56a951bb3b8ed2b134",
        "odin_tt": "e56450cd91b07005a3944a795bc51e5a80366580d6525a5fedd139ebab799f7a710e0944c4962fd5c3d06981a8abd558541a079803617c39eb9bf631d0f7bd0541f0117ff4c5decb25ead26b18079ca1",
        "__ac_nonce": "06ace4e6500e683a85719",
        "__ac_signature": "_02B4Z6wo00f01vHgk9gAAIDAyQzw12XjVdrx0JdAANbD64",
    },
    "msToken": "E7hDXPgowjq7BqxB_EgCByvA5Lc_c0a2b0DnUn5xGFV9dkE9Ql_kchh1XbOZIQwMxYEf0WYbADW_51GqNlV504CbvNucd_NUUin3sPN7y9RQZRxLJhD-2scDH2u_vGIul6MnnaM70Y0jj7McEWg-n6Xl9xxJ2eIuhM-XKiQo1Vmp",  # 必填：localStorage 的 xmst
    "screen_width": 1920,
    "screen_height": 1080,
}

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def build_stage1_url(ms_token: str, max_cursor: str = "0", count: str = "18") -> str:
    params = [
        ("device_platform", "webapp"),
        ("aid", "6383"),
        ("channel", "channel_pc_web"),
        ("sec_user_id", SEC_USER_ID),
        ("max_cursor", max_cursor),
        ("count", count),
        ("from_user_page", "1"),
        ("msToken", ms_token),
    ]
    return API_URL + "?" + urlencode(params)


def sign_url(stage1_url: str) -> str:
    """调用 Node sign.js 完成两段式签名，返回最终可请求的 URL。"""
    cookies = CONFIG["cookies"]
    ms_token = CONFIG["msToken"]
    s_v_web_id = cookies["s_v_web_id"]

    cfg = {
        "pageUrl": PAGE_URL,
        "ua": UA,
        "screen": {
            "width": CONFIG.get("screen_width", 1920),
            "height": CONFIG.get("screen_height", 1080),
        },
        "cookies": {
            "UIFID": cookies.get("UIFID", ""),
            "s_v_web_id": s_v_web_id,
            "msToken": ms_token,
        },
        "localStorage": {"xmst": ms_token},
        "ssr": {"app": {"odin": {"user_id": "0", "user_unique_id": "0"}}},
        "uifid": cookies.get("UIFID", ""),
        "stage1Url": stage1_url,
        "appendQuery": f"verifyFp={s_v_web_id}&fp={s_v_web_id}",
    }

    proc = subprocess.run(
        ["node", str(SCRIPT_DIR / "sign.js")],
        input=json.dumps(cfg, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(SCRIPT_DIR),
        timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sign.js 执行失败: {(proc.stderr or '').strip()[-500:]}")

    # 解析 artifact：标记行下一行是 JSON
    lines = proc.stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "===== DOUYIN SIGN ARTIFACT =====" and i + 1 < len(lines):
            artifact = json.loads(lines[i + 1].strip())
            if artifact.get("ok") and artifact.get("url"):
                return artifact["url"]
            raise RuntimeError(f"签名失败: {json.dumps(artifact.get('notes'), ensure_ascii=False)[:500]}")
    raise RuntimeError("sign.js 未输出有效 artifact")


def build_headers(referer: str) -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "referer": referer,
        "user-agent": UA,
        "sec-ch-ua": '"Chromium";v="154", "Google Chrome";v="154", "Not)A;Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def build_cookie_str() -> str:
    cookies = CONFIG["cookies"]
    pairs = []
    for name, value in cookies.items():
        if value:
            pairs.append(f"{name}={value}")
    if CONFIG["msToken"]:
        pairs.append(f"msToken={CONFIG['msToken']}")
    return "; ".join(pairs)


def fetch_aweme_list(signed_url: str, referer: str):
    """用 curl_cffi 发送真实请求，返回解析后的 JSON。"""
    headers = build_headers(referer)
    headers["cookie"] = build_cookie_str()
    resp = cffi_requests.get(
        signed_url,
        headers=headers,
        impersonate="chrome",  # TLS 指纹伪装成 Chrome
        timeout=30,
    )
    return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    if not CONFIG["cookies"].get("UIFID") or not CONFIG["cookies"].get("s_v_web_id") or not CONFIG["msToken"]:
        print("[!] 请先在 CONFIG 里填入 UIFID / s_v_web_id / msToken 三个必填项")
        sys.exit(1)

    max_cursor = "0"
    for page in range(1, 4):  # 默认抓 3 页
        print(f"\n===== 第 {page} 页 (max_cursor={max_cursor}) =====")

        stage1_url = build_stage1_url(CONFIG["msToken"], max_cursor=max_cursor)
        print("[*] 生成签名 ...")
        signed_url = sign_url(stage1_url)
        print("[*] 签名完成，a_bogus 与 x-secsdk-web-signature 已追加")

        status, data = fetch_aweme_list(signed_url, referer=PAGE_URL)
        print(f"[*] HTTP {status}")

        if status != 200:
            print(f"    status_code={data.get('status_code')} message={data.get('status_msg')}")
            break

        aweme_list = data.get("aweme_list") or []
        print(f"    本页视频数: {len(aweme_list)}  has_more={data.get('has_more')}")

        for item in aweme_list:
            desc = (item.get("desc") or "").strip()
            aweme_id = item.get("aweme_id")
            print(f"    - [{aweme_id}] {desc[:40]}")

        max_cursor = str(data.get("max_cursor", 0))
        if not data.get("has_more") or not max_cursor or max_cursor == "0":
            print("    没有更多了")
            break


if __name__ == "__main__":
    main()
