"""Capture a full cookie set (all bangkokair cookies + reese84 expires) and
test whether it can be replayed directly, without any renewal."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import main as m
from mint_seed import _executable_path

WEB = "https://digital.bangkokair.com"
PAGE = WEB + "/booking/availability/0"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "js_reverse_cache", "pool_token.json")


def mint_all(headless=True):
    from camoufox.sync_api import Camoufox
    kwargs = {
        "headless": headless, "os": "windows", "locale": "en-US",
        "humanize": True, "geoip": False, "block_webrtc": False,
    }
    exe = _executable_path()
    if exe:
        kwargs["executable_path"] = exe
    with Camoufox(**kwargs) as browser:
        page = browser.new_page()
        page.goto(PAGE, wait_until="domcontentloaded", timeout=45000)
        token = None
        for _ in range(30):
            page.wait_for_timeout(1000)
            for c in page.context.cookies():
                if c.get("name") == "reese84" and "bangkokair" in (c.get("domain") or ""):
                    token = c.get("value")
                    break
            if token:
                break
        cookies = [c for c in page.context.cookies()
                   if "bangkokair" in (c.get("domain") or "")]
        try:
            page.close()
        except Exception:
            pass
        return token, cookies


def replay(cookies, token, label):
    s = m._session()
    try:
        for c in cookies:
            s.cookies.set(c["name"], c["value"],
                          domain=c.get("domain") or ".bangkokair.com",
                          path=c.get("path") or "/")
        if token and not any(c["name"] == "reese84" for c in cookies):
            m.install_cookie(s, token)
        ok, status, size = m.verify_token(s)
        line = "%-22s verify=%-5s status=%s size=%s" % (label, ok, status, size)
        if ok:
            try:
                at, exp = m.get_access_token(s, token)
                doc = m.search_air_bounds(s, at, token, "BKK", "HKT", "2026-11-15")
                line += "  => offers=%d" % len(m.parse_offers(doc))
            except Exception as e:
                line += "  => ERR %s" % str(e)[:70]
        print(line)
        return ok
    finally:
        s.close()


def main():
    print("[1] minting with Camoufox and capturing ALL cookies ...")
    t0 = time.time()
    token, cookies = mint_all()
    if not token:
        print("    FAILED: no reese84 cookie")
        return 1
    r84 = next((c for c in cookies if c["name"] == "reese84"), {})
    exp = r84.get("expires")
    print("    token len=%d  cookies=%d  solve=%.1fs" % (len(token), len(cookies), time.time() - t0))
    print("    reese84 expires=%s" % exp)
    if exp and exp > 0:
        left = exp - time.time()
        print("    => cookie lifetime = %.1f hours (%.1f days)" % (left / 3600.0, left / 86400.0))
    for c in cookies:
        e = c.get("expires")
        print("      %-22s len=%-5d expires=%s" % (c["name"], len(c["value"]),
                                                   ("%.1fd" % ((e - time.time()) / 86400.0)) if e and e > 0 else e))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"token": token, "cookies": cookies, "savedAt": time.time()}, fh, indent=1)
    print("    saved -> %s" % OUT)

    print("\n[2] replaying ALL cookies directly (no renewal) ...")
    replay(cookies, token, "all-cookies")

    print("\n[3] replaying reese84 only (what main.py does) ...")
    replay([], token, "reese84-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
