# -*- coding: utf-8 -*-
"""Bounded JSONL network relay for the Adidas NV8 probe."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

from curl_cffi import requests

ORIGIN = "https://www.adidas.com.hk"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
AUDIT_PATH = Path(__file__).with_name("relay_audit.jsonl")
MAX_REQUESTS = int(os.environ.get("ADIDAS_RELAY_MAX_REQUESTS", "4"))
BROKER_HOST = os.environ.get("ADIDAS_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("ADIDAS_BROKER_PORT", "0"))
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Origin": ORIGIN,
    "Referer": ORIGIN + "/",
}


def main() -> None:
    if BROKER_PORT <= 0:
        raise SystemExit("ADIDAS_BROKER_PORT must point to the Python-owned session broker")
    with socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=30) as connection:
        reader = connection.makefile("r", encoding="utf-8", newline="\n")
        writer = connection.makefile("w", encoding="utf-8", newline="\n")
        for line in sys.stdin:
            if not line.strip():
                continue
            writer.write(line)
            writer.flush()
            response = reader.readline()
            if not response:
                raise RuntimeError("Python session broker disconnected")
            sys.stdout.write(response)
            sys.stdout.flush()


def send(session: requests.Session, request: dict[str, Any]) -> dict[str, Any]:
    body = base64.b64decode(request["body"]) if request.get("body") else None
    headers = dict(HEADERS)
    for item in request.get("headers") or []:
        if isinstance(item, list) and len(item) == 2:
            name, value = str(item[0]), str(item[1])
            if name.lower() not in {"host", "content-length", "cookie", "user-agent", "connection"}:
                headers[name] = value
    response = session.request(
        method=str(request.get("method") or "GET"),
        url=str(request["url"]),
        headers=headers,
        data=body,
        timeout=30,
        allow_redirects=False,
    )
    return {
        "id": request.get("id"),
        "status": response.status_code,
        "statusText": "",
        "headers": [[str(name), str(value)] for name, value in response.headers.items()],
        "body": base64.b64encode(response.content or b"").decode("ascii"),
        "url": str(response.url),
    }


def audit(request: dict[str, Any], response: dict[str, Any], session: requests.Session, sequence: int) -> None:
    body = base64.b64decode(request["body"]) if request.get("body") else b""
    response_body = base64.b64decode(response.get("body") or "")
    response_headers = response.get("headers") or []
    set_cookie_names = [
        str(value).split("=", 1)[0].strip()
        for name, value in response_headers
        if str(name).lower() == "set-cookie"
    ]
    record = {
        "sequence": sequence,
        "method": request.get("method"),
        "url": request.get("url"),
        "request_body_length": len(body),
        "request_body_sha256": hashlib.sha256(body).hexdigest() if body else None,
        "status": response.get("status"),
        "response_body_length": len(response_body),
        "response_body_sha256": hashlib.sha256(response_body).hexdigest() if response_body else None,
        "set_cookie_names": set_cookie_names,
        "session_cookies": cookie_metadata(session.cookies.get_dict()),
        "server_timing": next((value for name, value in response_headers if str(name).lower() == "server-timing"), ""),
        "akamai_trace": any(str(name).lower() == "x-akamai-trace-id" for name, _ in response_headers),
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + "\n")


def cookie_metadata(cookies: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "length": len(value),
            "sha256_prefix": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
        }
        for name, value in sorted(cookies.items())
    }


if __name__ == "__main__":
    main()
