# -*- coding: utf-8 -*-
"""Adidas HK product collector and offline HTML parser.

The business endpoint returns server-rendered product HTML rather than JSON.
This module keeps parsing independent from the Akamai challenge workflow so a
captured page can be verified offline while live requests still use Python.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from curl_cffi import requests

ROOT = Path(__file__).resolve().parent
TARGET = "https://www.adidas.com.hk/"
SEARCH_ENDPOINT = (
    "https://www.adidas.com.hk/on/demandware.store/"
    "Sites-adidas-HK-Site/en_HK/Search-UpdateGrid"
)
QUICKVIEW_ENDPOINT = (
    "https://www.adidas.com.hk/on/demandware.store/"
    "Sites-adidas-HK-Site/en_HK/Globale-Cache"
)
# Keep the transport tuple coherent with the successful browser baseline:
# Camoufox reports Firefox 135, and curl_cffi has a matching impersonation.
IMPERSONATE = os.environ.get("ADIDAS_IMPERSONATE", "firefox135")
UA = os.environ.get(
    "ADIDAS_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _classes(attrs: dict[str, str]) -> set[str]:
    return set(attrs.get("class", "").split())


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _as_price(value: Any) -> Any:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


class _ProductParser(HTMLParser):
    """Extract product cards without requiring a third-party HTML library."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.products: list[dict[str, Any]] = []
        self.page_number: int | None = None
        self._product: dict[str, Any] | None = None
        self._product_depth = 0
        self._captures: list[dict[str, Any]] = []
        self._color_variant: dict[str, Any] | None = None
        self._open_tags: list[tuple[str, set[str]]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = _classes(attrs)

        if "data-page-number" in attrs and self.page_number is None:
            try:
                self.page_number = int(attrs["data-page-number"])
            except ValueError:
                pass

        if self._product is None and tag == "div" and "product" in classes:
            tracking = attrs.get("data-tracking-product-tile", "")
            try:
                tracking_data = json.loads(tracking)
            except json.JSONDecodeError:
                tracking_data = {}
            self._product = {
                "product_id": tracking_data.get("product_id") or attrs.get("data-pid"),
                "product_model_id": tracking_data.get("product_model_id"),
                "name": tracking_data.get("product_name"),
                "price_type": tracking_data.get("product_price_type"),
                "gender": tracking_data.get("product_gender"),
                "sport": tracking_data.get("product_sport"),
                "brand": tracking_data.get("product_brand"),
                "category": tracking_data.get("product_category"),
                "product_type": tracking_data.get("product_type", []),
                "status": tracking_data.get("product_status") or attrs.get("data-product-status"),
                "price": _as_price(tracking_data.get("product_price")),
                "discount_percentage": _as_price(tracking_data.get("product_discount_percentage")),
                "rating": tracking_data.get("product_rating") or None,
                "reviews": tracking_data.get("product_reviews") or None,
                "url": None,
                "images": {},
                "badges": [],
                "gender_division": None,
                "color_variants": [],
            }
            self._product_depth = 1
            self._open_tags.append((tag, classes))
            return

        if self._product is None:
            return

        if tag not in VOID_TAGS:
            self._product_depth += 1
            self._open_tags.append((tag, classes))
        if tag == "img" and "tile-image" in classes:
            image_key = "default" if "image-default" in classes else "alternate"
            image_url = attrs.get("data-src") or attrs.get("src")
            if image_url:
                self._product["images"][image_key] = urljoin(self.base_url, image_url)

        if tag == "a" and self._has_open_class("pdp-link"):
            self._captures.append({"tag": tag, "kind": "name_link", "text": "", "href": attrs.get("href", "")})
        elif tag == "span" and "value" in classes and self._has_open_class("sales"):
            self._captures.append({"tag": tag, "kind": "price", "text": ""})
        elif tag == "span" and "product-badges-text" in classes:
            self._captures.append({"tag": tag, "kind": "badge", "text": ""})
        elif tag == "div" and "gender-division" in classes:
            self._captures.append({"tag": tag, "kind": "gender_division", "text": ""})

        if tag == "a" and "color-attribute" in classes:
            self._color_variant = {
                "product_id": attrs.get("data-pid") or None,
                "url": urljoin(self.base_url, attrs.get("data-pdpurl", "")),
                "variation_url": urljoin(self.base_url, attrs.get("data-url", "")),
                "label": attrs.get("aria-label", ""),
                "color": None,
                "image": None,
            }
        if tag == "img" and self._color_variant is not None:
            self._color_variant["color"] = attrs.get("data-attr-value") or None
            if attrs.get("src"):
                self._color_variant["image"] = urljoin(self.base_url, attrs["src"])

    def _has_open_class(self, class_name: str) -> bool:
        return any(class_name in classes for _, classes in self._open_tags)

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        for capture in self._captures:
            capture["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if self._product is None:
            return
        if tag in VOID_TAGS:
            return

        for capture in self._captures[::-1]:
            if capture["tag"] == tag:
                self._captures.remove(capture)
                value = _clean_text(capture["text"])
                if capture["kind"] == "name_link":
                    self._product["name"] = self._product["name"] or value
                    self._product["url"] = urljoin(self.base_url, capture["href"])
                elif capture["kind"] == "price" and value:
                    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", value)
                    if match:
                        self._product["price"] = _as_price(match.group(0).replace(",", ""))
                elif capture["kind"] == "badge" and value and value not in self._product["badges"]:
                    self._product["badges"].append(value)
                elif capture["kind"] == "gender_division" and value:
                    self._product["gender_division"] = value
                break

        if tag == "a" and self._color_variant is not None:
            if self._color_variant["product_id"]:
                self._product["color_variants"].append(self._color_variant)
            self._color_variant = None

        if self._open_tags:
            self._open_tags.pop()
        self._product_depth -= 1
        if self._product_depth == 0:
            self._product["name"] = _clean_text(self._product.get("name") or "")
            self.products.append(self._product)
            self._product = None
            self._captures.clear()
            self._color_variant = None
            self._open_tags.clear()


def parse_product_html(html: str, base_url: str = TARGET) -> dict[str, Any]:
    parser = _ProductParser(base_url)
    parser.feed(html)
    parser.close()
    return {"page_number": parser.page_number, "products": parser.products}


def build_search_url(cgid: str = "men", start: int = 0, size: int = 48, pmin: str = "0.01") -> str:
    params = {
        "cgid": cgid,
        "pmin": pmin,
        "start": str(start),
        "sz": str(size),
    }
    selected_url = f"{SEARCH_ENDPOINT}?{urlencode(params)}"
    params["selectedUrl"] = selected_url
    return f"{SEARCH_ENDPOINT}?{urlencode(params)}"


def build_quickview_url(product_id: str) -> str:
    return f"{QUICKVIEW_ENDPOINT}?{urlencode({'remoteIncludeUrl': 'Product-ShowQuickView', 'pid': product_id, 'ajax': 'true'})}"


def _detail_image_urls(images: Any, base_url: str) -> dict[str, Any]:
    if not isinstance(images, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in images.items():
        if isinstance(value, list):
            result[key] = [urljoin(base_url, item) if isinstance(item, str) else item for item in value]
        elif isinstance(value, str):
            result[key] = urljoin(base_url, value)
        else:
            result[key] = value
    return result


def parse_product_detail(data: dict[str, Any], source_url: str) -> dict[str, Any]:
    """Normalize the JSON payload returned by Product-ShowQuickView."""
    product = data.get("product") or {}
    sales = ((product.get("price") or {}).get("sales") or {})
    sizes: list[dict[str, Any]] = []
    for attribute in product.get("variationAttributes") or []:
        attribute_id = attribute.get("id") or attribute.get("attributeId")
        for value in attribute.get("values") or []:
            sizes.append(
                {
                    "attribute_id": attribute_id,
                    "attribute_name": attribute.get("displayName"),
                    "id": value.get("id"),
                    "value": value.get("value"),
                    "label": value.get("displayValue"),
                    "selected": bool(value.get("selected")),
                    "selectable": bool(value.get("selectable")),
                    "sku": value.get("attID"),
                    "url": value.get("url"),
                }
            )

    return {
        "product_id": product.get("id"),
        "name": product.get("productName"),
        "brand": product.get("brand"),
        "product_type": product.get("productType"),
        "canonical": product.get("canonical"),
        "price": _as_price(sales.get("value")),
        "currency": sales.get("currency"),
        "formatted_price": sales.get("formatted"),
        "color": product.get("color"),
        "available": product.get("available"),
        "ready_to_order": product.get("readyToOrder"),
        "online": product.get("online"),
        "availability": product.get("availability"),
        "color_stock": product.get("colorStock") or [],
        "sizes": sizes,
        "images": _detail_image_urls(product.get("images"), source_url),
        "short_description": product.get("shortDescription"),
        "long_description": product.get("longDescription"),
        "bullets": product.get("bullets") or [],
        "promotions": product.get("promotions") or [],
        "size_chart_id": product.get("sizeChartId"),
        "size_chart_symbol": product.get("sizeChartSymbol"),
        "min_order_quantity": product.get("minOrderQuantity"),
        "max_order_quantity": product.get("maxOrderQuantity"),
        "selected_product_url": product.get("selectedProductUrl"),
        "source_url": source_url,
    }


def _headers(referer: str | None = None, ajax: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": UA,
        "Accept": "*/*" if ajax else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }
    if not ajax:
        headers["Upgrade-Insecure-Requests"] = "1"
    else:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        headers["Referer"] = referer
    return headers


def fetch_page(url: str, session: Any | None = None) -> dict[str, Any]:
    owns_session = session is None
    session = session or requests.Session(impersonate=IMPERSONATE, default_headers=False)
    try:
        response = session.get(
            url,
            headers=_headers(TARGET),
            cookies=None,
            timeout=30,
            allow_redirects=True,
        )
        text = response.text
        lower = text.lower()
        parsed = parse_product_html(text, str(response.url)) if response.status_code == 200 else {"page_number": None, "products": []}
        challenge = (
            response.status_code in (403, 429)
            or "security issue was automatically identified" in lower
            or "akamai" in lower and "challenge" in lower
        )
        return {
            "url": str(response.url),
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_length": len(response.content or b""),
            "challenge": challenge,
            "business_page": bool(parsed["products"]),
            "cookie_names": sorted(session.cookies.get_dict()),
            "page_number": parsed["page_number"],
            "products": parsed["products"],
        }
    finally:
        if owns_session:
            session.close()


def fetch_product_detail(product_id: str, session: Any | None = None) -> dict[str, Any]:
    owns_session = session is None
    session = session or requests.Session(impersonate=IMPERSONATE, default_headers=False)
    url = build_quickview_url(product_id)
    try:
        response = session.get(
            url,
            headers=_headers(TARGET, ajax=True),
            timeout=30,
            allow_redirects=True,
        )
        content_type = response.headers.get("content-type", "")
        try:
            payload = response.json() if response.status_code == 200 else {}
        except ValueError:
            payload = {}
        detail = parse_product_detail(payload, str(response.url)) if payload.get("product") else None
        lower = response.text.lower()
        return {
            "product_id": product_id,
            "url": str(response.url),
            "status": response.status_code,
            "content_type": content_type,
            "body_length": len(response.content or b""),
            "challenge": response.status_code in (403, 429) or "security issue was automatically identified" in lower,
            "detail": detail,
        }
    finally:
        if owns_session:
            session.close()


def collect_product_details(product_ids: list[str]) -> dict[str, Any]:
    session = requests.Session(impersonate=IMPERSONATE, default_headers=False)
    cookie = os.environ.get("ADIDAS_COOKIE")
    if cookie:
        session.headers.update({"Cookie": cookie})
    results = []
    try:
        # Warm the same session on the business list endpoint so Akamai and
        # Demandware session cookies are established before Quick View calls.
        warmup = fetch_page(build_search_url("men", 0, 48), session)
        for product_id in product_ids:
            result = fetch_product_detail(product_id, session)
            results.append(result)
            if result["challenge"] and result["detail"] is None:
                break
    finally:
        session.close()
    return {
        "warmup": {key: value for key, value in warmup.items() if key != "products"},
        "details": results,
    }


def collect_pages(cgid: str, start: int, size: int, pages: int) -> dict[str, Any]:
    session = requests.Session(impersonate=IMPERSONATE, default_headers=False)
    cookie = os.environ.get("ADIDAS_COOKIE")
    if cookie:
        session.headers.update({"Cookie": cookie})
    all_products: dict[str, dict[str, Any]] = {}
    page_results = []
    try:
        for page_index in range(pages):
            page_start = start + page_index * size
            result = fetch_page(build_search_url(cgid, page_start, size), session)
            page_results.append({key: value for key, value in result.items() if key != "products"})
            if result["challenge"] and not result["products"]:
                break
            for product in result["products"]:
                product_id = product.get("product_id")
                if product_id:
                    all_products[product_id] = product
    finally:
        session.close()
    return {"pages": page_results, "products": list(all_products.values())}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Adidas HK product HTML, list products, or fetch product details")
    parser.add_argument("--html", type=Path, help="parse a saved HTML response instead of making a request")
    parser.add_argument("--url", default=None, help="fetch this exact URL")
    parser.add_argument("--akamai-protocol", action="store_true", help="run current Akamai challenge in isolated NV8 and relay HTTP through one Python Session")
    parser.add_argument("--product", action="append", dest="product_ids", help="fetch one product detail; repeat for multiple IDs")
    parser.add_argument("--products", dest="product_ids_csv", help="comma-separated product IDs for detail collection")
    parser.add_argument("--cgid", default="men")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--size", type=int, default=48)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    return parser.parse_args()


def collect_akamai_protocol() -> dict[str, Any]:
    """Execute the current challenge in NV8 while Python owns all live HTTP."""
    runner = ROOT / "js_reverse_cache" / "akamai" / "run_same_session.py"
    completed = subprocess.run(
        [sys.executable, str(runner)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    final = None
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if candidate.get("step") == "final":
            final = candidate
            break
    if final is None:
        return {
            "success": False,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-2000:],
        }
    return {**final, "success": completed.returncode == 0 and bool(final.get("business_success"))}


if __name__ == "__main__":
    # Windows PowerShell/CMD may expose a GBK stdout; detail payloads can
    # contain product text outside that code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _arguments()
    if args.html:
        result = parse_product_html(args.html.read_text(encoding="utf-8"))
    elif args.akamai_protocol:
        result = collect_akamai_protocol()
    elif args.product_ids or args.product_ids_csv:
        product_ids = list(args.product_ids or [])
        if args.product_ids_csv:
            product_ids.extend(item.strip() for item in args.product_ids_csv.split(",") if item.strip())
        result = collect_product_details(product_ids)
    elif args.url:
        result = fetch_page(args.url)
    else:
        result = collect_pages(args.cgid, args.start, args.size, args.pages)
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
