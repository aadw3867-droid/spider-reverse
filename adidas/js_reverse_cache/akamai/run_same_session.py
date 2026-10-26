from __future__ import annotations

import hashlib
import json
import os
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import main as product_collector  # noqa: E402
ORIGIN = "https://www.adidas.com.hk/"
TOTAL_BUDGET = 12
SENSOR_BUDGET = 8
BUSINESS_BUDGET = 2
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Upgrade-Insecure-Requests": "1",
}


def cookie_metadata(cookies: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {"length": len(value), "sha256_prefix": hashlib.sha256(value.encode()).hexdigest()[:16]}
        for name, value in sorted(cookies.items())
    }


class RelayHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        owner: BrokerServer = self.server  # type: ignore[assignment]
        for raw_line in self.rfile:
            if not raw_line.strip():
                continue
            try:
                request = json.loads(raw_line)
                response = owner.forward(request)
            except Exception as error:
                response = {"error": f"{type(error).__name__}: {error}"}
            self.wfile.write((json.dumps(response, ensure_ascii=True) + "\n").encode("utf-8"))
            self.wfile.flush()


class BrokerServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, session):
        super().__init__(address, RelayHandler)
        self.session = session
        self.count = 0
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def forward(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.count >= SENSOR_BUDGET:
                return {"id": request.get("id"), "error": "session request budget exhausted"}
            self.count += 1
            sequence = self.count
        body = __import__("base64").b64decode(request["body"]) if request.get("body") else None
        headers = {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Origin": "https://www.adidas.com.hk",
            "Referer": ORIGIN,
        }
        for item in request.get("headers") or []:
            if isinstance(item, list) and len(item) == 2:
                name, value = str(item[0]), str(item[1])
                if name.lower() not in {"host", "content-length", "cookie", "user-agent", "connection"}:
                    headers[name] = value
        response = self.session.request(
            method=str(request.get("method") or "GET"),
            url=str(request["url"]),
            headers=headers,
            data=body,
            timeout=30,
            allow_redirects=False,
        )
        response_headers = [[str(k), str(v)] for k, v in response.headers.items()]
        payload = response.content or b""
        sensor_body = body or b""
        if body:
            try:
                outer = json.loads(body.decode("utf-8"))
                if isinstance(outer, dict) and isinstance(outer.get("body"), str):
                    sensor_body = outer["body"].encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        self.records.append({
            "sequence": sequence,
            "method": request.get("method"),
            "url": request.get("url"),
            "wire_body_length": len(body or b""),
            "wire_body_sha256": hashlib.sha256(body).hexdigest() if body else None,
            "sensor_body_length": len(sensor_body),
            "sensor_body_sha256": hashlib.sha256(sensor_body).hexdigest() if sensor_body else None,
            "status": response.status_code,
            "response_bytes": len(payload),
            "set_cookie_names": [v.split("=", 1)[0] for k, v in response_headers if k.lower() == "set-cookie"],
            "cookie_meta": cookie_metadata(self.session.cookies.get_dict()),
            "server_timing": response.headers.get("server-timing", ""),
        })
        return {
            "id": request.get("id"),
            "status": response.status_code,
            "statusText": "",
            "headers": response_headers,
            "body": __import__("base64").b64encode(payload).decode("ascii"),
            "url": str(response.url),
        }


def main() -> int:
    session = requests.Session(impersonate="firefox135", default_headers=False)
    relay: BrokerServer | None = None
    relay_thread: threading.Thread | None = None
    try:
        home = session.get(ORIGIN, headers=HEADERS, timeout=30, allow_redirects=True)
        print(json.dumps({"step": "home", "status": home.status_code, "bytes": len(home.content or b""),
                          "cookies": cookie_metadata(session.cookies.get_dict())}, ensure_ascii=True))
        import re
        match = re.search(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", home.text, re.I)
        if not match:
            print("challenge script not found")
            return 2
        script_url = urljoin(str(home.url), match.group(1))
        script_response = session.get(script_url, headers={**HEADERS, "Accept": "*/*", "Referer": ORIGIN}, timeout=30)
        script = script_response.content or b""
        digest = hashlib.sha256(script).hexdigest()
        print(json.dumps({"step": "script", "status": script_response.status_code, "url": script_url,
                          "bytes": len(script), "sha256": digest, "execution_scope": "approved-current-rotating-script"}, ensure_ascii=True))
        if script_response.status_code != 200 or not script:
            print("STOP: current challenge script was not successfully fetched")
            return 3
        script_path = CACHE / "current_challenge.js"
        script_path.write_bytes(script)

        relay = BrokerServer(("127.0.0.1", 0), session)
        relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
        relay_thread.start()
        environment = os.environ.copy()
        environment.update({
            "ADIDAS_CHALLENGE_URL": script_url,
            "ADIDAS_CHALLENGE_PATH": str(script_path),
            "ADIDAS_BROKER_PORT": str(relay.server_address[1]),
            "ADIDAS_RELAY_MAX_REQUESTS": str(SENSOR_BUDGET),
        })
        node_runner = CACHE / "run_current_challenge.mjs"
        execution = subprocess.run(["node", str(node_runner)], cwd=ROOT, env=environment,
                                  capture_output=True, text=True, timeout=90)
        print(json.dumps({"step": "nv8", "returncode": execution.returncode,
                          "stdout": execution.stdout[-12000:], "stderr": execution.stderr[-3000:],
                          "sensor_requests": len(relay.records)}, ensure_ascii=True))

        if len(relay.records) > SENSOR_BUDGET or 2 + len(relay.records) >= TOTAL_BUDGET:
            print("STOP: request budget leaves no room for business verification")
            return 4
        list_url = (
            "https://www.adidas.com.hk/on/demandware.store/Sites-adidas-HK-Site/en_HK/Search-UpdateGrid"
            "?cgid=men&pmin=0.01&start=0&sz=48&selectedUrl="
            "https%3A%2F%2Fwww.adidas.com.hk%2Fon%2Fdemandware.store%2FSites-adidas-HK-Site%2Fen_HK%2FSearch-UpdateGrid%3Fcgid%3Dmen%26pmin%3D0.01%26start%3D0%26sz%3D48"
        )
        business = session.get(list_url, headers={**HEADERS, "Referer": ORIGIN}, timeout=30)
        parsed_list = product_collector.parse_product_html(business.text, str(business.url)) if business.status_code == 200 else {"products": []}
        products = parsed_list["products"]
        is_business = business.status_code == 200 and "text/html" in business.headers.get("content-type", "") and bool(products)
        business_result: dict[str, Any] = {"step": "business_list", "status": business.status_code,
                          "content_type": business.headers.get("content-type", ""),
                          "body_bytes": len(business.content or b""),
                          "page_number": parsed_list.get("page_number"),
                          "product_count": len(products),
                          "business_success": is_business,
                          "cookie_meta": cookie_metadata(session.cookies.get_dict())}
        print(json.dumps(business_result, ensure_ascii=True))
        product_id: str | None = None
        detail_result: dict[str, Any] | None = None
        if is_business and BUSINESS_BUDGET > 1 and 3 + len(relay.records) < TOTAL_BUDGET:
            if products:
                product_id = str(products[0].get("product_id", ""))
                detail_url = (
                    "https://www.adidas.com.hk/on/demandware.store/Sites-adidas-HK-Site/en_HK/Globale-Cache"
                    "?remoteIncludeUrl=Product-ShowQuickView&pid=" + product_id + "&ajax=true"
                )
                detail_response = session.get(
                    detail_url,
                    headers={**HEADERS, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest", "Referer": ORIGIN},
                    timeout=30,
                )
                try:
                    detail_payload = detail_response.json()
                except ValueError:
                    detail_payload = {}
                product = detail_payload.get("product") or {}
                detail_success = detail_response.status_code == 200 and str(product.get("id", "")) == product_id
                detail_result = {
                    "step": "business_detail",
                    "product_id": product_id,
                    "status": detail_response.status_code,
                    "content_type": detail_response.headers.get("content-type", ""),
                    "body_bytes": len(detail_response.content or b""),
                    "detail_success": detail_success,
                    "cookie_meta": cookie_metadata(session.cookies.get_dict()),
                }
                if detail_success:
                    detail_result["detail"] = product_collector.parse_product_detail(detail_payload, str(detail_response.url))
                print(json.dumps(detail_result, ensure_ascii=True))
                is_business = is_business and detail_success
        print(json.dumps({"step": "final", "relay_request_count": len(relay.records),
                          "http_request_count": 3 + len(relay.records) + (1 if detail_result else 0),
                          "business_success": is_business,
                          "product_id": product_id,
                          "page_number": parsed_list.get("page_number"),
                          "product_count": len(products),
                          "first_products": products[:5],
                          "detail": detail_result.get("detail") if detail_result else None,
                          "relay_records": relay.records}, ensure_ascii=True))
        return 0 if is_business else 5
    finally:
        if relay is not None:
            relay.shutdown()
            relay.server_close()
        if relay_thread is not None:
            relay_thread.join(timeout=2)
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
