"""Bangkok Airways — Imperva/Reese84 token renewal + availability search (pure Python).

Architecture
------------
The Reese84 first-issue token requires a full browser fingerprint interrogation.
However, once ONE genuine token exists, the server accepts a plain renewal:

    GET  /booking/availability/0            (no reese84 cookie)  -> interstitial + random path
    POST /<random-path>?d=digital.bangkokair.com
         body = "<old token>"   (a JSON string literal, Content-Type: text/plain)
      -> {"token": "...", "renewInSec": N, "cookieDomain": "bangkokair.com"}

A token with renewInSec > 0 can be renewed, but renewInSec is only a *suggested
renewal interval* — it is NOT the token's expiry. The reese84 cookie a real
browser sets carries an expires of ~30 days, and that token is accepted directly
for the whole period. So the normal path is: mint once, then use the token as-is.

Renewal is only a fallback for when direct use is rejected. Measured: a renewed
token stops being renewable after ~13 minutes, so never prefer renewal over a
browser-minted token.

The seed token must be supplied by the caller, or minted:
    set RE84_SEED=<token>        or        --seed-file <path>
    --mint          mint a fresh seed when none is supplied
    --auto-mint     mint automatically when there is no seed, or when the
                    cached token is rejected and cannot be renewed

Usage
-----
    python main.py --from BKK --to HKT --date 2026-11-15 --auto-mint
    python main.py --from BKK --to HKT --date 2026-11-15 --fare PGSAVER --json
    python main.py --check-token
"""

import argparse
import json
import os
import re
import sys
import uuid

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from curl_cffi import requests

WEB = "https://digital.bangkokair.com"
PAGE = WEB + "/booking/availability/0"
API = "https://api-des.bangkokair.com"

# Cached seed token: written after every successful renew so later runs never
# need a browser. A renewed token is itself a valid seed, so this self-refreshes.
# Override with RE84_SEED_CACHE=<path>; set it to "" to disable the cache.
_CACHE_ENV = os.environ.get("RE84_SEED_CACHE")
DEFAULT_SEED_FILE = (
    _CACHE_ENV if _CACHE_ENV is not None
    else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "js_reverse_cache", "seed_token.txt")
)

CLIENT_ID = "GOsS3AbywB1UUsiTBqmS03GR2eYX5pZn"
CLIENT_SECRET = "CcKzc5n82S2ya6Zv"

FARE_FAMILIES = ("PGPROMO", "PGFLEX")
FARE_CODES = ("PGPROMO", "PGSAVER", "PGFREEDOM", "PGBLUE")

# Observed on the live API (2026-11): PGBLUE exists ONLY in business cabin,
# the other three codes only in eco. Requesting a mismatched pair yields an
# empty result set that looks like "sold out" but is really invalid.
CODE_CABIN = {
    "PGPROMO": "eco",
    "PGSAVER": "eco",
    "PGFREEDOM": "eco",
    "PGBLUE": "business",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")
CH = {
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
NAV = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    **CH,
}
RENEW = {
    "User-Agent": UA,
    "Accept": "application/json; charset=utf-8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "text/plain; charset=utf-8",
    "Origin": WEB,
    "Referer": PAGE,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    **CH,
}
API_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Origin": WEB,
    "Referer": WEB + "/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    **CH,
}

PATH_RE = re.compile(r'scriptElement\.src\s*=\s*"([^"]+)"')


class Reese84Error(RuntimeError):
    pass


def _session():
    return requests.Session(impersonate="chrome136", default_headers=False)


def _challenge_url(sess):
    """Fetch the interstitial without a reese84 cookie and extract the challenge path.

    The interstitial is only served when the request carries no valid reese84
    cookie, so we temporarily drop it (keeping incap_ses etc.) and restore it.
    Without this, renewing a session that already holds a valid token fails
    with "no challenge path found".
    """
    saved = None
    for c in list(sess.cookies.jar):
        if c.name == "reese84":
            saved = dict(name=c.name, value=c.value,
                         domain=c.domain, path=c.path or "/")
            sess.cookies.jar.clear(c.domain, c.path or "/", c.name)
    try:
        r = sess.get(PAGE, headers=NAV, timeout=45, allow_redirects=False)
        body = r.content.decode("utf-8", "replace")
        m = PATH_RE.search(body)
        if not m:
            if "Pardon Our Interruption" not in body and r.status_code == 200:
                raise Reese84Error("no challenge path found (page may already be unblocked)")
            raise Reese84Error("no challenge path in interstitial (status %s)" % r.status_code)
        return WEB + m.group(1) + "?d=digital.bangkokair.com"
    finally:
        if saved:
            install_cookie(sess, saved["value"], saved["domain"].lstrip("."))


def renew_token(seed, sess=None):
    """Renew a genuine reese84 token. Returns (token, renew_in_sec, cookie_domain)."""
    if not seed:
        raise Reese84Error("empty seed token")
    own = sess is None
    s = sess or _session()
    try:
        url = _challenge_url(s)
        r = s.post(url, headers=RENEW, data=json.dumps(seed), timeout=45, allow_redirects=False)
        if r.status_code != 200:
            raise Reese84Error("renew HTTP %s: %s" % (r.status_code, (r.text or "")[:160]))
        try:
            d = r.json()
        except Exception:
            raise Reese84Error("renew returned non-JSON: %s" % (r.text or "")[:160])
        tok = d.get("token") or ""
        secs = d.get("renewInSec") or 0
        if not tok or not secs:
            raise Reese84Error(
                "seed token is not a genuine token (renewInSec=%r). "
                "Obtain a fresh seed from a real browser session." % (secs,)
            )
        return tok, int(secs), d.get("cookieDomain") or "bangkokair.com"
    finally:
        if own:
            s.close()


def install_cookie(sess, token, domain="bangkokair.com"):
    sess.cookies.set("reese84", token, domain="." + domain.lstrip("."), path="/")


def page_kind(sess):
    """Classify the page: 'spa', 'block', 'interstitial', or 'unknown'."""
    r = sess.get(PAGE, headers=NAV, timeout=45, allow_redirects=False)
    body = r.content.decode("utf-8", "replace")
    if "Pardon Our Interruption" in body:
        return "block", r.status_code, len(r.content), body
    if "scriptElement.src" in body:
        return "interstitial", r.status_code, len(r.content), body
    if "<app-root" in body or "main." in body:
        return "spa", r.status_code, len(r.content), body
    return "unknown", r.status_code, len(r.content), body


def verify_token(sess):
    """Return True only when the real SPA is served (not a block/interstitial page).

    NOTE: a valid reese84 token is NOT sufficient on its own - the interstitial
    page also returns HTTP 200 with a ~6 KB body, so status code and size alone
    are not enough. We must look at the markup.
    """
    kind, status, size, _ = page_kind(sess)
    return kind == "spa", status, size


def get_access_token(sess, reese84):
    h = dict(API_HEADERS)
    h["Accept"] = "application/json"
    h["Content-Type"] = "application/x-www-form-urlencoded"
    h["x-d-token"] = reese84
    body = ("client_id=%s&client_secret=%s&grant_type=client_credentials"
            % (CLIENT_ID, CLIENT_SECRET))
    r = sess.post(API + "/v1/security/oauth2/token", headers=h, data=body,
                  timeout=45, allow_redirects=False)
    if r.status_code != 200:
        raise Reese84Error("oauth HTTP %s: %s" % (r.status_code, (r.text or "")[:160]))
    d = r.json()
    at = d.get("access_token")
    if not at:
        raise Reese84Error("oauth response missing access_token")
    return at, int(d.get("expires_in") or 0)


def _air_bounds_call(sess, access_token, reese84, itineraries,
                     fare_family, passengers, selected_bound_id=None):
    h = dict(API_HEADERS)
    h["Accept"] = "application/json, text/plain, */*"
    h["Content-Type"] = "application/json;charset=UTF-8"
    h["Authorization"] = "Bearer " + access_token
    h["x-d-token"] = reese84
    h["Ama-Client-Ref"] = str(uuid.uuid4())
    payload = {
        "commercialFareFamilies": [fare_family],
        "itineraries": itineraries,
        "travelers": [{"passengerTypeCode": "ADT"} for _ in range(max(1, passengers))],
        "searchPreferences": {"showSoldOut": False, "showMilesPrice": False},
    }
    if selected_bound_id:
        payload["selectedBoundId"] = selected_bound_id
    r = sess.post(API + "/v2/search/air-bounds", headers=h,
                  data=json.dumps(payload, separators=(",", ":")),
                  timeout=60, allow_redirects=False)
    if r.status_code != 200:
        raise Reese84Error("air-bounds HTTP %s: %s" % (r.status_code, (r.text or "")[:200]))
    doc = r.json()
    errs = doc.get("errors")
    if errs:
        first = errs[0] if isinstance(errs, list) and errs else {}
        raise Reese84Error("air-bounds error %s: %s"
                           % (first.get("code"), first.get("title")))
    return doc


def search_air_bounds(sess, access_token, reese84, origin, dest, date,
                      fare_family="PGPROMO", passengers=1, return_date=None,
                      outbound_bound_id=None):
    """One-way, or round trip via the two-step construction-mode flow.

    Round trip (mirrors the SPA's callFlexPremium):
      step 1: itineraries=[out(isRequestedBound=True), ret(False)]      -> outbound bounds
      step 2: itineraries=[out(False), ret(True)] + selectedBoundId=<outbound airBoundId>
    """
    out_it = {
        "originLocationCode": origin.upper(),
        "destinationLocationCode": dest.upper(),
        "departureDateTime": "%sT00:00:00.000" % date,
        "isRequestedBound": True,
    }
    if not return_date:
        return _air_bounds_call(sess, access_token, reese84, [out_it],
                                fare_family, passengers)

    ret_it = {
        "originLocationCode": dest.upper(),
        "destinationLocationCode": origin.upper(),
        "departureDateTime": "%sT00:00:00.000" % return_date,
    }
    step1 = _air_bounds_call(
        sess, access_token, reese84,
        [dict(out_it), dict(ret_it, isRequestedBound=False)],
        fare_family, passengers)
    offers1 = parse_offers(step1)
    if not offers1:
        return step1
    bound_id = outbound_bound_id
    if bound_id:
        known = {o.get("airBoundId") for o in offers1}
        if bound_id not in known:
            raise Reese84Error("outbound bound %r not in outbound results" % bound_id)
    else:
        bound_id = offers1[0].get("airBoundId")
    step2 = _air_bounds_call(
        sess, access_token, reese84,
        [dict(out_it, isRequestedBound=False), dict(ret_it, isRequestedBound=True)],
        fare_family, passengers, selected_bound_id=bound_id)
    step2["_roundTrip"] = {
        "selectedBoundId": bound_id,
        "outbound": offers1,
        "returnDate": return_date,
    }
    return step2


def parse_offers(doc):
    """Flatten airBoundGroups into one dict per offer."""
    flights = (doc.get("dictionaries") or {}).get("flight") or {}
    services = (doc.get("dictionaries") or {}).get("service") or {}
    out = []
    for grp in (doc.get("data") or {}).get("airBoundGroups") or []:
        bd = grp.get("boundDetails") or {}
        seg_ids = [s.get("flightId") for s in (bd.get("segments") or [])]
        for bound in grp.get("airBounds") or []:
            total = ((bound.get("prices") or {}).get("totalPrices") or [{}])[0]
            av = (bound.get("availabilityDetails") or [{}])[0]
            svc_codes = [s.get("serviceCode") for s in (bound.get("services") or [])]
            segs = []
            for fid in seg_ids:
                f = flights.get(fid) or {}
                dep = f.get("departure") or {}
                arr = f.get("arrival") or {}
                segs.append({
                    "flightId": fid,
                    "flightNumber": (f.get("marketingAirlineCode") or "") + (f.get("marketingFlightNumber") or ""),
                    "from": dep.get("locationCode"),
                    "to": arr.get("locationCode"),
                    "departure": dep.get("dateTime"),
                    "arrival": arr.get("dateTime"),
                    "aircraft": f.get("aircraftCode"),
                    "durationSec": f.get("duration"),
                })
            baggage = []
            for code in svc_codes:
                svc = services.get(code) or {}
                for pol in svc.get("baggagePolicyDescriptions") or []:
                    baggage.append("%s%s" % (pol.get("quantity"), (pol.get("weightUnit") or "")[:2]))
            out.append({
                "fareFamily": bound.get("fareFamilyCode"),
                "airBoundId": bound.get("airBoundId"),
                "cheapest": bool(bound.get("isCheapestOffer")),
                "cabin": av.get("cabin"),
                "bookingClass": av.get("bookingClass"),
                "status": av.get("statusCode"),
                "seatsLeft": av.get("quota"),
                "currency": total.get("currencyCode"),
                "base": total.get("base"),
                "taxes": total.get("totalTaxes"),
                "total": total.get("total"),
                "baggage": baggage,
                "segments": segs,
            })
    out.sort(key=lambda x: (x.get("total") or 0))
    return out


def fmt_duration(sec):
    if not sec:
        return "?"
    h, m = divmod(int(sec) // 60, 60)
    return "%dh%02dm" % (h, m) if h else "%dm" % m


def filter_offers(offers, fare_code=None, cabin=None):
    """Filter by sub fare family (PGPROMO/PGSAVER/PGFREEDOM/PGBLUE) and/or cabin."""
    out = offers
    if fare_code:
        want = fare_code.upper()
        out = [o for o in out if (o.get("fareFamily") or "").upper() == want]
    if cabin:
        want = cabin.lower()
        out = [o for o in out if (o.get("cabin") or "").lower() == want]
    return out


def cabin_for_code(fare_code):
    return CODE_CABIN.get((fare_code or "").upper())


def _filter_note(args):
    bits = []
    if args.fare_code:
        bits.append("fareCode=" + args.fare_code)
    if args.cabin:
        bits.append("cabin=" + args.cabin)
    return (" [" + " ".join(bits) + "]") if bits else ""


def _mint_seed(headful=False):
    """Mint a fresh seed with Camoufox. Returns the token, or "" on failure."""
    try:
        from mint_seed import mint
    except Exception as e:
        print("error: cannot import mint_seed: %s" % e, file=sys.stderr)
        return ""
    seed = mint(headless=not headful) or ""
    if seed:
        print("minted seed: len=%d" % len(seed), file=sys.stderr)
    return seed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bangkok Airways availability (pure Python)")
    ap.add_argument("--from", dest="origin", default="BKK")
    ap.add_argument("--to", dest="dest", default="HKT")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: tomorrow+14)")
    ap.add_argument("--return-date", dest="return_date", default=None,
                    help="YYYY-MM-DD for a round trip")
    ap.add_argument("--fare", default="PGPROMO", choices=FARE_FAMILIES,
                    help="commercial fare family")
    ap.add_argument("--fare-code", default=None, choices=FARE_CODES,
                    help="filter results by sub fare family")
    ap.add_argument("--cabin", default=None, choices=("eco", "business"),
                    help="filter results by cabin")
    ap.add_argument("--outbound-bound", default=None,
                    help="airBoundId of the chosen outbound leg (round trip only)")
    ap.add_argument("--pax", type=int, default=1)
    ap.add_argument("--seed-file", default=None)
    ap.add_argument("--mint", action="store_true",
                    help="mint a fresh seed with Camoufox when no seed is provided")
    ap.add_argument("--auto-mint", dest="auto_mint", action="store_true",
                    help="mint a fresh seed automatically when there is no seed "
                         "or the cached/expired seed can no longer be renewed")
    ap.add_argument("--headful", action="store_true", help="show browser while minting")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check-token", action="store_true")
    args = ap.parse_args(argv)

    if args.return_date:
        if not args.date:
            import datetime
            args.date = (datetime.date.today()
                         + datetime.timedelta(days=14)).isoformat()
        if args.return_date < args.date:
            print("error: --return-date %s is before --date %s (the API rejects "
                  "this with error 1112 INVALID ITINERARY)"
                  % (args.return_date, args.date), file=sys.stderr)
            return 2

    if args.fare_code:
        implied = cabin_for_code(args.fare_code)
        if args.cabin and implied and args.cabin.lower() != implied:
            print("warning: %s only exists in the %s cabin; ignoring --cabin %s"
                  % (args.fare_code, implied, args.cabin), file=sys.stderr)
            args.cabin = implied

    seed = os.environ.get("RE84_SEED", "").strip()
    if not seed and args.seed_file:
        with open(args.seed_file, encoding="utf-8") as fh:
            seed = fh.read().strip()
    if not seed and args.mint:
        print("no seed supplied; minting one with Camoufox ...", file=sys.stderr)
        seed = _mint_seed(args.headful)
        if not seed:
            print("error: mint produced no reese84 cookie", file=sys.stderr)
            return 2
    if not seed and os.path.exists(DEFAULT_SEED_FILE):
        with open(DEFAULT_SEED_FILE, encoding="utf-8") as fh:
            seed = fh.read().strip()
        if seed:
            print("using cached seed: %s" % DEFAULT_SEED_FILE, file=sys.stderr)
    if not seed and args.auto_mint:
        print("no seed available; auto-minting one with Camoufox ...", file=sys.stderr)
        seed = _mint_seed(args.headful)
    if not seed:
        print("error: no seed token. Set RE84_SEED, pass --seed-file, or use --mint.",
              file=sys.stderr)
        return 2

    sess = _session()
    try:
        token = seed
        install_cookie(sess, token)
        ok, status, size = verify_token(sess)
        print("token check (direct): ok=%s status=%s size=%d" % (ok, status, size),
              file=sys.stderr)

        if not ok:
            # A token minted by a real browser carries a ~30-day cookie expiry,
            # so it is normally usable directly. Only fall back to renewal when
            # direct use is rejected.
            try:
                token, secs, domain = renew_token(seed, sess)
                print("renewed: len=%d renewInSec=%d domain=%s" % (len(token), secs, domain),
                      file=sys.stderr)
                install_cookie(sess, token, domain)
                ok, status, size = verify_token(sess)
                print("token check (renewed): ok=%s status=%s size=%d" % (ok, status, size),
                      file=sys.stderr)
            except Exception as e:
                print("renew failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)

        if not ok and args.auto_mint:
            print("token rejected; auto-minting a fresh one with Camoufox ...",
                  file=sys.stderr)
            fresh = _mint_seed(args.headful)
            if not fresh:
                print("error: auto-mint produced no reese84 cookie", file=sys.stderr)
                return 2
            token = fresh
            install_cookie(sess, token)
            ok, status, size = verify_token(sess)
            print("token check (minted): ok=%s status=%s size=%d" % (ok, status, size),
                  file=sys.stderr)

        if not ok:
            print("error: no usable reese84 token", file=sys.stderr)
            return 3
        if DEFAULT_SEED_FILE:
            try:
                os.makedirs(os.path.dirname(DEFAULT_SEED_FILE), exist_ok=True)
                with open(DEFAULT_SEED_FILE, "w", encoding="utf-8") as fh:
                    fh.write(token)
            except OSError as e:
                print("warning: could not cache seed: %s" % e, file=sys.stderr)
        if args.check_token:
            return 0

        date = args.date
        if not date:
            import datetime
            date = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()

        at, exp = get_access_token(sess, token)
        print("oauth ok: access_token len=%d expires_in=%d" % (len(at), exp), file=sys.stderr)

        doc = search_air_bounds(sess, at, token, args.origin, args.dest, date,
                               fare_family=args.fare, passengers=args.pax,
                               return_date=args.return_date,
                               outbound_bound_id=args.outbound_bound)
        offers = filter_offers(parse_offers(doc), args.fare_code, args.cabin)
        rt = doc.get("_roundTrip")
        if rt:
            rt["outbound"] = filter_offers(rt["outbound"], args.fare_code, args.cabin)
        print("offers: %d%s%s" % (len(offers), " (return leg)" if rt else "",
                                  _filter_note(args)), file=sys.stderr)

        if args.json:
            out = {
                "origin": args.origin.upper(), "destination": args.dest.upper(),
                "date": date, "returnDate": args.return_date,
                "fareFamily": args.fare, "offers": offers,
            }
            if rt:
                out["selectedBoundId"] = rt["selectedBoundId"]
                out["outbound"] = rt["outbound"]
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        def show(rows, header):
            if not rows:
                return
            print(header)
            print("  %-10s %-6s %-6s %-6s %-5s %-8s %-4s %s" %
                  ("FLIGHT", "DEPART", "ARRIVE", "CLASS", "SEATS", "TOTAL", "CUR", "ROUTE"))
            for o in rows:
                seg = o["segments"][0] if o["segments"] else {}
                dep = (seg.get("departure") or "")[11:16]
                arr = (seg.get("arrival") or "")[11:16]
                route = " > ".join("%s-%s" % (s.get("from") or "", s.get("to") or "")
                                   for s in o["segments"])
                flights = "+".join(s.get("flightNumber") or "" for s in o["segments"])
                print("  %-10s %-6s %-6s %-6s %-5s %-8s %-4s %s" % (
                    flights, dep, arr, o.get("bookingClass") or "",
                    o.get("seatsLeft") if o.get("seatsLeft") is not None else "?",
                    o.get("total"), o.get("currency"), route))

        if not offers:
            print("no offers")
            return 0
        if rt:
            print("ROUND TRIP %s->%s %s / %s->%s %s  (%s)"
                  % (args.origin.upper(), args.dest.upper(), date,
                     args.dest.upper(), args.origin.upper(), rt["returnDate"], args.fare))
            print("selected outbound bound: %s" % rt["selectedBoundId"])
            show(rt["outbound"][:5], "\nOUTBOUND (top 5 by price):")
            show(offers, "\nRETURN:")
        else:
            print("ONE WAY %s->%s %s  (%s)"
                  % (args.origin.upper(), args.dest.upper(), date, args.fare))
            show(offers, "")
        return 0
    except Reese84Error as e:
        print("error: %s" % e, file=sys.stderr)
        return 4
    finally:
        sess.close()


if __name__ == "__main__":
    sys.exit(main())
