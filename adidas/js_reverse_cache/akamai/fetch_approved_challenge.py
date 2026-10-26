from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests


ORIGIN = "https://www.adidas.com.hk/"
APPROVED_SHA256 = "95be855f08779384a016759e319ef52534d421818c3a4b2b680757af01e9a9e5"
OUTPUT = Path(__file__).with_name("current_challenge.js")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Upgrade-Insecure-Requests": "1",
}


def main() -> None:
    session = requests.Session(impersonate="firefox135", default_headers=False)
    try:
        response = session.get(ORIGIN, headers=HEADERS, timeout=30, allow_redirects=True)
        print({
            "step": "home",
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_bytes": len(response.content or b""),
            "cookie_names": sorted(session.cookies.get_dict()),
        })
        match = re.search(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", response.text, re.I)
        if not match:
            print({"challenge_script_found": False})
            return
        script_url = urljoin(str(response.url), match.group(1))
        script_response = session.get(
            script_url,
            headers={**HEADERS, "Accept": "*/*", "Referer": ORIGIN},
            timeout=30,
            allow_redirects=True,
        )
        body = script_response.content or b""
        digest = hashlib.sha256(body).hexdigest()
        matches_approved = script_response.status_code == 200 and digest == APPROVED_SHA256
        print({
            "step": "challenge_script",
            "status": script_response.status_code,
            "url": script_url,
            "content_type": script_response.headers.get("content-type", ""),
            "body_bytes": len(body),
            "sha256": digest,
            "approved_hash_match": matches_approved,
        })
        if body:
            OUTPUT.write_bytes(body)
    finally:
        session.close()


if __name__ == "__main__":
    main()
