# -*- coding: utf-8 -*-
"""Browser-free T'way flight availability collector.

Python/curl_cffi owns all HTTP and cookies. IV8 runs the current Akamai
collector and returns its XHR intent through a synchronous parent bridge.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
from http.cookies import SimpleCookie
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests

from utils.iv8_silent import import_iv8_silent
from utils.logger import logger

iv8 = import_iv8_silent()

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "js_reverse_cache" / "akamai"
BASE = "https://www.trinityairways.com"
LANDING = "https://www.twayair.com/"
QUEUE = "https://csnf.trinityairways.com/ts.wseq"
UA = os.environ.get(
    "AKAMAI_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
)
PROFILE = os.environ.get("AKAMAI_CURL_PROFILE", "firefox135")
HOST = "www.trinityairways.com"
ORIGIN = "https://" + HOST
# Fixed ordering of the main-form field set. The site serialises
# #airAvailabilityRQ in DOM order; server-side validation rejects a reordered
# body with HTTP 400, so this list is the contract.
FORM_PREFIX = ("searchDate", "promoCode", "cmpIndDiv", "defaultPromoCode", "bookingTicket",
               "tripType", "bookingType", "promoCodeDetails.promoCode", "validPromoCode")
DEPARTURE = os.environ.get("AKAMAI_DEPARTURE", "ICN").upper()
ARRIVAL = os.environ.get("AKAMAI_ARRIVAL", "KIX").upper()
FLIGHT_DATE = os.environ.get("AKAMAI_FLIGHT_DATE", (date.today() + timedelta(days=7)).isoformat())
MAX_REQUESTS = int(os.environ.get("AKAMAI_MAX_TOTAL_REQUESTS", "100"))
MAX_RETRIES = 1
FARE_NAMES = {"EventFare": "event", "SmartFare": "smart", "NormalFare": "normal", "BizFare": "business"}
AIRPORT_NAMES = {
    "ICN": "인천", "KIX": "오사카", "GMP": "김포", "PUS": "부산", "CJU": "제주",
    "NRT": "도쿄", "HND": "도쿄", "FUK": "후쿠오카", "NGO": "나고야", "CTS": "삿포로",
    "OKA": "오키나와", "TAE": "대구", "CJJ": "청주", "KWJ": "광주", "RSU": "여수",
}
SOLD_OUT_TEXT = "매진"
BAGGAGE_RE = re.compile(r"묵료\s*위탁수하물\s*:\s*([^\s]+)|무료\s*위탁수하물\s*:\s*([^\s]+)|위탁수하물\s*:\s*([^\s]+)")


class CollectorError(RuntimeError):
    pass


class ExitAdmissionError(CollectorError):
    pass


class FlightInventoryError(CollectorError):
    pass


class RequestBudget:
    def __init__(self, maximum: int):
        if maximum < 1:
            raise ValueError("AKAMAI_MAX_TOTAL_REQUESTS must be positive")
        self.maximum = maximum
        self.used = 0

    def consume(self, label: str) -> None:
        if self.used >= self.maximum:
            raise CollectorError(f"request budget exhausted before {label}: {self.used}/{self.maximum}")
        self.used += 1


def _headers(referer: str | None = None, *, document: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }
    if document:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers["Upgrade-Insecure-Requests"] = "1"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "same-origin" if referer else "none"
        if referer:
            headers["Sec-Fetch-User"] = "?1"
    else:
        headers["Accept"] = "*/*"
        if referer:
            headers["Referer"] = referer
    if referer:
        headers["Referer"] = referer
    return headers


def _visible_cookie_lines(response: Any) -> list[str]:
    try:
        set_cookies = response.headers.get_list("set-cookie")
    except Exception:
        item = response.headers.get("set-cookie")
        set_cookies = [item] if item else []
    lines = []
    for header in set_cookies:
        parsed = SimpleCookie()
        try:
            parsed.load(str(header))
        except Exception:
            continue
        if not parsed:
            continue
        for name, morsel in parsed.items():
            if morsel["httponly"]:
                continue
            parts = [f"{name}={morsel.value}", f"Path={morsel['path'] or '/'}"]
            if morsel["domain"]:
                parts.append(f"Domain={morsel['domain']}")
            if morsel["secure"]:
                parts.append("Secure")
            if morsel["samesite"]:
                parts.append(f"SameSite={morsel['samesite']}")
            lines.append("; ".join(parts))
    return lines


class HttpClient:
    def __init__(self, session: Any, budget: RequestBudget):
        self.session = session
        self.budget = budget
        self.records: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                data: Any = None, params: dict[str, Any] | None = None, label: str = "http",
                allow_redirects: bool = False):
        self.budget.consume(label)
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers or {},
                    data=data,
                    params=params,
                    timeout=30,
                    allow_redirects=allow_redirects,
                )
                for hop in response.history:
                    self.budget.consume(f"redirect:{label}")
                    self.records.append({
                        "method": method,
                        "url": _redact_url(str(hop.url)),
                        "status": hop.status_code,
                        "redirect": True,
                        "location_host": urllib.parse.urlsplit(hop.headers.get("location", "")).hostname,
                    })
                self.records.append({
                    "method": method,
                    "url": _redact_url(str(response.url)),
                    "status": response.status_code,
                    "body_bytes": len(response.content or b""),
                    "content_type": response.headers.get("content-type", ""),
                    "set_cookie_names": [line.split("=", 1)[0] for line in _visible_cookie_lines(response)],
                })
                if response.status_code in (403, 429) or b"Access Denied" in (response.content or b""):
                    if url.startswith(BASE):
                        raise ExitAdmissionError(f"Akamai denied {method} {_redact_url(str(response.url))} ({response.status_code})")
                return response
            except ExitAdmissionError:
                raise
            except Exception as error:
                last_error = error
                if attempt >= MAX_RETRIES:
                    break
                time.sleep(0.5 * (attempt + 1))
        raise CollectorError(f"{label} transport failed after bounded retry: {type(last_error).__name__}")


def _redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<query-redacted>" if parsed.query else "", ""))


def _cookie_metadata(session: Any) -> dict[str, dict[str, Any]]:
    import hashlib
    return {
        name: {"length": len(value), "sha256_prefix": hashlib.sha256(value.encode()).hexdigest()[:12]}
        for name, value in sorted(session.cookies.get_dict().items())
    }


def _is_challenge(html_text: str) -> bool:
    """True only for the interstitial Akamai challenge document.

    The gated shell is a ~2.6 KB sec-if-cpt page. The trusted application page
    is ~1 MB, also mentions ``bazadebezolkohpepadr`` (pixel bootstrap) and
    carries ``_csrf``, so those tokens alone do not indicate a challenge.
    """
    if "sec-if-cpt" not in html_text:
        return False
    return 'name="_csrf"' not in html_text


def _has_csrf(html_text: str) -> bool:
    return 'name="_csrf"' in html_text


def _extract_collector(html_text: str, page_url: str) -> tuple[str, str, str, str] | None:
    """Return the Akamai challenge/collector script declared by a gated page.

    The gated document embeds exactly one same-origin script URL carrying a
    ``t=<challengeId>`` query. jQuery bundles and the ``/akam/13/`` pixel are
    not collectors, so they are excluded explicitly.
    """
    soup = BeautifulSoup(html_text, "lxml")
    for script in soup.find_all("script", src=True):
        raw = html.unescape(script["src"])
        src = urllib.parse.urljoin(page_url, raw)
        parsed = urllib.parse.urlsplit(src)
        if parsed.netloc not in {"www.twayair.com", "www.trinityairways.com"}:
            continue
        if "/akam/13/" in parsed.path or "netfunnel" in parsed.path.lower():
            continue
        if "jquery" in parsed.path.lower():
            continue
        if "t=" not in parsed.query:
            continue
        return raw, src, parsed.path, raw
    return None


def _build_iv8_environment(page_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(page_url)
    return {
        "location": {
            "href": page_url,
            "origin": f"{parsed.scheme}://{parsed.netloc}",
            "protocol": f"{parsed.scheme}:",
            "host": parsed.netloc,
            "hostname": parsed.hostname or "",
            "pathname": parsed.path or "/",
            "search": f"?{parsed.query}" if parsed.query else "",
            "hash": "",
        },
        "navigator": {"userAgent": UA, "platform": "Win32", "language": "ko-KR", "languages": ["ko-KR", "ko", "en-US", "en"], "webdriver": False},
    }


def _parse_availability(page_html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(page_html, "lxml")
    flights = []
    for item in soup.select("li.price_list.section_list_item"):
        button = item.select_one("button.bul_air_info")
        segments = item.select(".segmentInfo")
        if not button or not segments:
            continue
        primary = segments[0]
        inputs = item.select("input.tripInfo")
        fares = []
        for index, box in enumerate(item.select(".rate_box")):
            fare_input = inputs[index] if index < len(inputs) else None
            segment = box.select_one(".segmentInfo")
            price_text = box.select_one(".rate_price")
            price_text = price_text.get_text(" ", strip=True) if price_text else ""
            box_text = box.get_text(" ", strip=True)
            price_match = re.search(r"([A-Z]{3})\s*([\d,]+)", price_text)
            seats_match = re.search(r"(\d+)\s*석", price_text)
            baggage_match = BAGGAGE_RE.search(box_text)
            baggage = next((value for value in baggage_match.groups() if value), None) if baggage_match else None
            raw_type = str(fare_input.get("data-faretype") or "") if fare_input else ""
            fares.append({
                "fare_type": FARE_NAMES.get(raw_type, raw_type),
                "booking_class": str(segment.get("data-bookingclass") or "") if segment else None,
                "currency": price_match.group(1) if price_match else "KRW",
                "price": int(price_match.group(2).replace(",", "")) if price_match else None,
                "seats": int(seats_match.group(1)) if seats_match else 0,
                "sold_out": bool(box.select_one(".soldout, .soldout_txt") or SOLD_OUT_TEXT in price_text),
                "cabin_baggage_kg": 10,
                "checked_baggage": baggage,
            })
        flights.append({
            "flight_number": button.get("data-dispflightnumber") or button.get_text(" ", strip=True),
            "aircraft": primary.get("data-aircraftprovider"),
            "date": primary.get("data-flightdate"),
            "departure": {"airport": primary.get("data-departureairportcode"), "time": primary.get("data-departuretime")},
            "arrival": {"airport": primary.get("data-arrivalairportcode"), "time": primary.get("data-arrivaltime")},
            "duration": str(primary.get("data-journeytime") or ""),
            "stops": int(str(primary.get("data-stops") or "0")),
            "fares": fares,
        })
    return flights


class FlightCollector:
    def __init__(self, departure: str = DEPARTURE, arrival: str = ARRIVAL, flight_date: str = FLIGHT_DATE):
        if not re.fullmatch(r"[A-Z]{3}", departure) or not re.fullmatch(r"[A-Z]{3}", arrival):
            raise ValueError("departure and arrival must be 3-letter airport codes")
        date.fromisoformat(flight_date)
        self.departure = departure
        self.arrival = arrival
        self.flight_date = flight_date
        self.departure_name = AIRPORT_NAMES.get(departure, "")
        self.arrival_name = AIRPORT_NAMES.get(arrival, "")
        self.budget = RequestBudget(MAX_REQUESTS)
        self.session = requests.Session(impersonate=PROFILE, default_headers=False)
        self.client = HttpClient(self.session, self.budget)
        self.cookies_visible: list[str] = []
        self.queue_ticket: str | None = None
        self.stage_records: list[dict[str, Any]] = []

    def _request(self, method: str, url: str, **kwargs):
        response = self.client.request(method, url, **kwargs)
        self.cookies_visible.extend(_visible_cookie_lines(response))
        return response

    def enter_netfunnel(self) -> str:
        query = urllib.parse.urlencode({
            "opcode": "5101", "nfid": "0", "prefix": "NetFunnel.gRtype=5101;",
            "ttl": "0", "sid": "service_1", "aid": "H_LandingPage", "js": "yes",
        }, safe=";=") + "&" + str(int(time.time() * 1000))
        url = QUEUE + "?" + query
        response = self._request("GET", url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.trinityairways.com/"}, label="netfunnel_enter")
        match = re.search(r"5002:200:([^'\"\s;]+)", response.text)
        if not match:
            raise CollectorError(f"NetFunnel enter did not return 5002:200 ticket (HTTP {response.status_code})")
        ticket_envelope = match.group(1)
        ticket_match = re.search(r"(?:^|&)key=([^&]+)", ticket_envelope)
        if not ticket_match:
            raise CollectorError("NetFunnel enter envelope did not contain key")
        self.queue_ticket = urllib.parse.unquote(ticket_match.group(1))
        return self.queue_ticket

    def complete_netfunnel(self) -> None:
        if not self.queue_ticket:
            raise CollectorError("NetFunnel ticket missing before complete")
        params = urllib.parse.urlencode({
            "opcode": "5004", "key": self.queue_ticket, "nfid": "0",
            "prefix": "NetFunnel.gRtype=5004;", "sid": "service_1", "aid": "act_1", "js": "yes",
        }, safe=";=") + "&" + str(int(time.time() * 1000))
        response = self._request("GET", QUEUE + "?" + params,
                                 headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.trinityairways.com/"},
                                 label="netfunnel_complete")
        if response.status_code != 200:
            raise CollectorError(f"NetFunnel complete HTTP {response.status_code}")
        self.queue_ticket = None

    def fetch_page(self, url: str, referer: str | None = None):
        return self._request("GET", url, headers=_headers(referer, document=True), label="document", allow_redirects=True)

    def run_collector(self, page_url: str, page_html: str) -> dict[str, Any]:
        found = _extract_collector(page_html, page_url)
        if not found:
            return {"skipped": True, "reason": "current HTML declares no same-origin Akamai collector"}
        collector_src, collector_url, collector_path, raw_src = found
        script_response = self._request("GET", collector_url, headers=_headers(page_url), label="collector_script")
        if script_response.status_code != 200:
            raise CollectorError(f"collector script fetch HTTP {script_response.status_code}")
        collector_js = script_response.content.decode("utf-8", errors="replace")
        pixel_scripts = []
        page_soup = BeautifulSoup(page_html, "lxml")
        for tag in page_soup.find_all("script", src=True):
            pixel_url = urllib.parse.urljoin(page_url, html.unescape(tag["src"]))
            if "/akam/13/" not in urllib.parse.urlsplit(pixel_url).path:
                continue
            pixel_response = self._request("GET", pixel_url, headers=_headers(page_url), label="akamai_pixel_script")
            if pixel_response.status_code == 200:
                pixel_scripts.append((pixel_url, pixel_response.content.decode("utf-8", errors="replace")))
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "current_collector.js").write_bytes(script_response.content)
        collector_sha = __import__("hashlib").sha256(script_response.content).hexdigest()

        ctx = iv8.JSContext(mode="prod", environment=_build_iv8_environment(page_url),
                            config={"timezone": "Asia/Seoul", "time": {"mode": "system"}})
        ctx.enter()
        stage_stats: dict[str, Any] = {"xhr_count": 0, "sensor_posts": 0, "runtime_errors": [], "requests": []}

        def py_http(method: str, url: str, body: str | None, headers_json: str) -> str:
            resolved = urllib.parse.urljoin(page_url, url)
            parsed = urllib.parse.urlsplit(resolved)
            if parsed.hostname not in {"www.twayair.com", "www.trinityairways.com", "csnf.trinityairways.com"}:
                raise CollectorError("IV8 bridge rejected cross-origin XHR")
            headers = json.loads(headers_json or "{}")
            response = self._request(method, resolved, headers=headers, data=body, label="iv8_xhr")
            stage_stats["xhr_count"] += 1
            if method.upper() == "POST":
                stage_stats["sensor_posts"] += 1
            import hashlib
            request_bytes = (body or "").encode("utf-8")
            stage_stats["requests"].append({
                "method": method.upper(),
                "url": _redact_url(resolved),
                "body_bytes": len(request_bytes),
                "body_sha256_prefix": hashlib.sha256(request_bytes).hexdigest()[:16] if request_bytes else None,
                "status": response.status_code,
                "set_cookie_names": [line.split("=", 1)[0] for line in _visible_cookie_lines(response)],
            })
            visible = _visible_cookie_lines(response)
            return json.dumps({"status": response.status_code, "body": response.text,
                               "headers": {k.lower(): v for k, v in response.headers.items()},
                               "visible_cookies": visible}, ensure_ascii=False)

        ctx.expose(py_http, "pyHttp")
        page_resources = {collector_url: {"body": collector_js, "status": 200}}
        execution_soup = BeautifulSoup(page_html, "lxml")
        page_resources.update({url: {"body": source, "status": 200}
                               for url, source in pixel_scripts})
        netfunnel_url = getattr(self, "netfunnel_script_url", None)
        netfunnel_script = getattr(self, "netfunnel_script", None)
        if netfunnel_url and netfunnel_script:
            page_resources[netfunnel_url] = {"body": netfunnel_script, "status": 200}
        for script_tag in execution_soup.find_all("script"):
            if not script_tag.get("src") and "NetFunnel_Action" in script_tag.get_text():
                script_tag.decompose()
        collector_base_tag = execution_soup.new_tag("script")
        collector_base_tag.string = "window.__twayCollectorScriptUrl=" + json.dumps(collector_url, ensure_ascii=False) + ";"
        first_script = execution_soup.find("script")
        if first_script:
            first_script.insert_before(collector_base_tag)
        elif execution_soup.head:
            execution_soup.head.append(collector_base_tag)
        page_load_source = "window.__iv8__.page.load(" + json.dumps({
            "baseURL": page_url,
            "html": str(execution_soup),
            "resources": page_resources,
        }, ensure_ascii=False) + ")"
        bootstrap = """
        (function(){
          const nativeXHR = window.XMLHttpRequest;
          function BridgeXHR(){
            this.readyState=0; this.status=0; this.statusText=''; this.responseText=''; this.response='';
            this.responseType=''; this.withCredentials=false; this.timeout=0; this.onreadystatechange=null;
            this.onload=null; this.onerror=null; this.onprogress=null; this._listeners={}; this._headers={};
          }
          BridgeXHR.UNSENT=0; BridgeXHR.OPENED=1; BridgeXHR.HEADERS_RECEIVED=2; BridgeXHR.LOADING=3; BridgeXHR.DONE=4;
          BridgeXHR.prototype.addEventListener=function(n,f){(this._listeners[n]||(this._listeners[n]=[])).push(f)};
          BridgeXHR.prototype.removeEventListener=function(n,f){this._listeners[n]=(this._listeners[n]||[]).filter(x=>x!==f)};
          BridgeXHR.prototype.dispatchEvent=function(e){(this._listeners[e.type]||[]).forEach(f=>f.call(this,e));return true};
          BridgeXHR.prototype.open=function(m,u,a){this._method=String(m||'GET').toUpperCase();this._url=new URL(String(u),window.__twayCollectorScriptUrl||location.href).href;this._async=a!==false;this.readyState=1;if(this.onreadystatechange)this.onreadystatechange()};
          BridgeXHR.prototype.setRequestHeader=function(n,v){this._headers[String(n)]=String(v)};
          BridgeXHR.prototype.getResponseHeader=function(n){return (this._responseHeaders||{})[String(n).toLowerCase()]||null};
          BridgeXHR.prototype.getAllResponseHeaders=function(){return Object.entries(this._responseHeaders||{}).map(([k,v])=>k+': '+v).join('\\r\\n')};
          BridgeXHR.prototype.overrideMimeType=function(v){this._mime=v};
          BridgeXHR.prototype.abort=function(){this.readyState=0};
          BridgeXHR.prototype.send=function(body){
            const response=JSON.parse(window.__iv8__.data.pyHttp(this._method,this._url,body==null?null:String(body),JSON.stringify(this._headers)));
            (response.visible_cookies||[]).forEach(c=>{try{document.cookie=c}catch(e){}});
            this.status=response.status; this.statusText=String(response.status); this.responseText=response.body||''; this.response=this.responseText;
            this._responseHeaders=response.headers||{}; this.readyState=2;if(this.onreadystatechange)this.onreadystatechange();
            this.readyState=3;if(this.onprogress)this.onprogress({type:'progress',loaded:this.responseText.length,total:this.responseText.length,lengthComputable:true});
            this.readyState=4;if(this.onreadystatechange)this.onreadystatechange();if(this.onload)this.onload();this.dispatchEvent({type:'load'});this.dispatchEvent({type:'loadend'});
          };
          Object.defineProperty(BridgeXHR.prototype,'responseURL',{get(){return this._url||''}});
          Object.defineProperty(BridgeXHR.prototype,'responseXML',{get(){return null}});
          window.XMLHttpRequest=BridgeXHR;
        })();
        """
        try:
            ctx.eval(bootstrap, name="tway-xhr-bridge.js")
            ctx.eval("window.__twayCollectorScriptUrl=" + json.dumps(collector_url, ensure_ascii=False))
            visible_cookie_lines = []
            host = urllib.parse.urlsplit(page_url).hostname or ""
            for cookie in self.session.cookies.jar:
                cookie_domain = str(cookie.domain or "").lstrip(".")
                if cookie_domain and not (host == cookie_domain or host.endswith("." + cookie_domain)):
                    continue
                # HttpOnly cookies are seeded too: the sensor payload is derived
                # from the live cookie jar, not from what page JS could read.
                visible_cookie_lines.append(f"{cookie.name}={cookie.value}; Path={cookie.path or '/'}")
            for cookie_line in visible_cookie_lines:
                ctx.eval("document.cookie=" + json.dumps(cookie_line, ensure_ascii=False))
            ctx.eval(page_load_source, name="tway-page-load.js")
            quiet_steps = 0
            for _ in range(500):
                ctx.eval("window.__iv8__.eventLoop.sleep(50)")
                if stage_stats["xhr_count"]:
                    quiet_steps += 1
                    if quiet_steps >= 40:
                        break
            stats = {"settle_steps": min(500, quiet_steps if stage_stats["xhr_count"] else 500),
                     "document_ready_state": ctx.eval("document.readyState"),
                     "document_url": ctx.eval("document.URL")}
            return {"collector_url": collector_path, "collector_script_sha256": collector_sha,
                    "stats": stage_stats, "runtime": stats, "collector_requests": self.client.records[-stage_stats["xhr_count"]:]}
        finally:
            ctx.leave()
            ctx.close()

    def run(self) -> dict[str, Any]:
        landing = self._request("GET", LANDING, headers=_headers(document=True), label="landing", allow_redirects=False)
        if landing.status_code not in (200, 301, 302):
            raise ExitAdmissionError(f"landing status {landing.status_code}")
        root = self.fetch_page(BASE + "/", LANDING)
        if root.status_code != 200:
            raise ExitAdmissionError(f"root status {root.status_code}")
        main_page = self.fetch_page(BASE + "/app/main", BASE + "/")
        if main_page.status_code != 200:
            raise ExitAdmissionError(f"/app/main HTTP {main_page.status_code}")
        main_sensor: dict[str, Any] = {"skipped": True, "reason": "no challenge issued"}
        if _is_challenge(main_page.text):
            main_sensor = self.run_collector(str(main_page.url), main_page.text)
            time.sleep(1.0)
            main_page = self.fetch_page(BASE + "/app/main", BASE + "/")
        if main_page.status_code != 200:
            raise ExitAdmissionError(f"/app/main HTTP {main_page.status_code} after sensor")
        if b"Access Denied" in (main_page.content or b""):
            raise ExitAdmissionError("/app/main returned EdgeSuite Access Denied")
        if _is_challenge(main_page.text):
            raise ExitAdmissionError("/app/main still gated by an unsolved Akamai challenge")
        return self.search_availability(main_page.url, main_page.text, {}, main_sensor)

    def queue_enter(self) -> str:
        query = urllib.parse.urlencode({
            "opcode": "5101", "nfid": "0", "prefix": "NetFunnel.gRtype=5101;", "ttl": "0",
            "sid": "service_1", "aid": "H_LandingPage", "js": "yes",
        }, safe=";=") + "&" + str(int(time.time() * 1000))
        url = QUEUE + "?" + query
        response = self._request("GET", url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.trinityairways.com/"}, label="netfunnel_enter")
        found = re.search(r"5002:200:([^'\"\s;]+)", response.text)
        if not found:
            raise CollectorError("NetFunnel enter did not return 5002:200 ticket")
        match = re.search(r"(?:^|&)key=([^&]+)", found.group(1))
        if not match:
            raise CollectorError("NetFunnel enter response lacks ticket key")
        return urllib.parse.unquote(match.group(1))

    def queue_complete(self, ticket: str) -> None:
        params = urllib.parse.urlencode({"opcode": "5004", "key": ticket, "nfid": "0",
                                         "prefix": "NetFunnel.gRtype=5004;", "sid": "service_1", "aid": "H_LandingPage",
                                         "js": "yes"}, safe=";=") + "&" + str(int(time.time() * 1000))
        response = self._request("GET", QUEUE + "?" + params,
                                 headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.trinityairways.com/"},
                                 label="netfunnel_complete")
        if response.status_code != 200:
            raise CollectorError(f"NetFunnel complete HTTP {response.status_code}")

    def build_form_fields(self, csrf: str) -> list[tuple[str, str]]:
        """Reproduce #airAvailabilityRQ in DOM order for a one-way search."""
        fields: list[tuple[str, str]] = [("_csrf", csrf), ("searchDate", date.today().strftime("%m%d")),
                                         ("promoCode", ""), ("cmpIndDiv", ""), ("defaultPromoCode", ""),
                                         ("bookingTicket", ""), ("tripType", "OW"), ("bookingType", "HI"),
                                         ("promoCodeDetails.promoCode", ""), ("validPromoCode", "")]
        for index in range(5):
            first = index == 0
            fields.extend([(f"availabilitySearches[{index}].depAirport", self.departure if first else ""),
                           (f"availabilitySearches[{index}].arrAirport", self.arrival if first else ""),
                           (f"availabilitySearches[{index}].flightDate", self.flight_date if first else "")])
        fields.extend([("paxCountDetails[0].paxCount", "1"), ("paxCountDetails[1].paxCount", "0"),
                       ("paxCountDetails[2].paxCount", "0")])
        for index in range(5):
            first = index == 0
            fields.extend([(f"availabilitySearches[{index}].depAirportName", self.departure_name if first else ""),
                           (f"availabilitySearches[{index}].arrAirportName", self.arrival_name if first else "")])
        fields.extend([("gaLocation", "메인"), ("pax", "1"), ("pax", "0"), ("pax", "0"),
                       ("deptAirportCode", self.departure), ("arriAirportCode", self.arrival),
                       ("schedule", self.flight_date)])
        return fields

    def search_availability(self, page_url: str, page_html: str, landing_sensor: dict[str, Any],
                            main_sensor: dict[str, Any]) -> dict[str, Any]:
        soup = BeautifulSoup(page_html, "lxml")
        csrf = soup.select_one("input[name=_csrf]")
        csrf_value = csrf.get("value") if csrf else None
        if not csrf_value:
            raise CollectorError("main page has no CSRF token")
        # The endpoint rejects a body whose brackets are left unencoded, so the
        # query string is percent-encoded field by field.
        fields = self.build_form_fields(csrf_value)
        query = urllib.parse.urlencode(fields, quote_via=urllib.parse.quote, safe="")

        xhr_headers = {**_headers(page_url), "X-Requested-With": "XMLHttpRequest",
                       "Accept": "application/json, text/javascript, */*; q=0.01",
                       "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}
        check = self._request("GET", BASE + "/ajax/booking/chkSaleRoute?" + query,
                              headers=xhr_headers, label="check_sale_route")
        try:
            check_payload = check.json()
        except ValueError:
            check_payload = {}
        if check_payload.get("success") is False:
            raise FlightInventoryError("chkSaleRoute says route/date is not on sale")

        choose = self._request("POST", BASE + "/app/booking/chooseItinerary", data=query.encode(),
                               headers={**_headers(page_url, document=True), "Referer": page_url,
                                        "Origin": ORIGIN,
                                        "Content-Type": "application/x-www-form-urlencoded",
                                        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
                                        "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1",
                                        "Upgrade-Insecure-Requests": "1"}, label="choose_itinerary")
        if choose.status_code in (403, 429) or b"Access Denied" in (choose.content or b""):
            raise ExitAdmissionError(f"chooseItinerary denied ({choose.status_code})")
        if choose.status_code != 200:
            raise CollectorError(f"chooseItinerary HTTP {choose.status_code}")
        choose_url = str(choose.url or BASE + "/app/booking/chooseItinerary")
        choose_soup = BeautifulSoup(choose.text, "lxml")
        meta_csrf = choose_soup.select_one("meta[name=_csrf]")
        choose_csrf = (meta_csrf.get("content") if meta_csrf else None) or csrf_value

        ticket = self.queue_enter()
        self.queue_complete(ticket)

        layer_body = urllib.parse.urlencode({"_csrf": choose_csrf, "pos": "KR", "currency": "KRW",
                                             "gaLocation": "메인", "cmpIndDiv": "I"},
                                            quote_via=urllib.parse.quote, safe="")
        availability = self._request("POST", BASE + "/app/booking/layerAvailabilityList",
                                     data=layer_body.encode(),
                                     headers={**_headers(choose_url), "Referer": choose_url, "Origin": ORIGIN,
                                              "X-Requested-With": "XMLHttpRequest",
                                              "Accept": "text/html, */*; q=0.01",
                                              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                              "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                                              "Sec-Fetch-Site": "same-origin"}, label="availability")
        if availability.status_code != 200:
            raise CollectorError(f"availability HTTP {availability.status_code}")
        flights = _parse_availability(availability.text)
        if not flights:
            raise FlightInventoryError(
                f"availability returned no flight/fare rows for {self.departure}-{self.arrival} "
                f"{self.flight_date}; likely empty inventory or an expired session")
        return {
            "success": True,
            "departure": self.departure,
            "arrival": self.arrival,
            "flight_date": self.flight_date,
            "landing_sensor": landing_sensor,
            "main_sensor": main_sensor,
            "netfunnel": {"completed": True},
            "check_sale_route": {"status": check.status_code,
                                 "keys": sorted(check_payload) if isinstance(check_payload, dict) else []},
            "choose_itinerary": {"status": choose.status_code, "bytes": len(choose.content or b"")},
            "availability": {"status": availability.status_code, "bytes": len(availability.content or b"")},
            "flight_count": len(flights),
            "flights": flights,
            "request_count": self.budget.used,
            "request_budget": self.budget.maximum,
            "cookie_meta": _cookie_metadata(self.session),
            "http_records": self.client.records,
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Browser-free T'way flight availability collector")
    parser.add_argument("--departure", default=DEPARTURE)
    parser.add_argument("--arrival", default=ARRIVAL)
    parser.add_argument("--date", default=FLIGHT_DATE)
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    args = parser.parse_args()
    collector = FlightCollector(args.departure, args.arrival, args.date)
    collector.budget = RequestBudget(args.max_requests)
    collector.client.budget = collector.budget
    try:
        result = collector.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        logger.info("collection failed: {}: {}", type(error).__name__, error)
        print(json.dumps({"success": False, "error_type": type(error).__name__, "error": str(error),
                          "request_count": collector.budget.used, "request_budget": collector.budget.maximum,
                          "http_records": collector.client.records}, ensure_ascii=False, indent=2))
        return 1
    finally:
        collector.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
