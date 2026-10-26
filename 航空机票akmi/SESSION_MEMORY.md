# T'way Airlines Akamai Flight Availability Task

## Status: SOLVED (browser-free, protocol only)

`python main.py --date 2026-10-31` returns real inventory in 11 requests. No browser, no
browser cookie import, no proxy. Verified on two routes:

- `ICN->KIX 2026-10-31` -> 4 flights (TW301 07:55/09:55 KRW 240,450; TW303 12:10/14:10 KRW 276,000;
  TW305 15:50/17:50 KRW 178,500; TW307 sold out)
- `ICN->NRT 2026-11-14` -> 5 flights (TW241/TW243/TW245/TW249/TW247, from KRW 189,900)

## User Goal

Target `https://www.twayair.com/` -> 301 -> `https://www.trinityairways.com/`. Browser-free
one-way availability/fare retrieval behind Akamai. Read-only: `chkSaleRoute`,
`chooseItinerary`, `layerAvailabilityList`. No purchase, seat hold, or payment.

## Root Cause of the Old 403 (the real fix)

Two independent problems, both now solved. Neither was a payload-quality problem.

1. **WAF/bot-score layer.** `/ajax/booking/*` and `/app/booking/*` are behind a path-level
   Akamai rule. It is cleared when `bm_sc` reaches grade `4~1~...`. That grade is produced only
   when the challenge sensor POST runs with the *session's full cookie jar*, including the
   HttpOnly cookies (`bm_s`, `ak_bmsc`). Dropping HttpOnly cookies from the IV8 `document.cookie`
   seed caps the result at grade `1`/`2` and the business paths stay 403 forever.

2. **Application layer (this was misdiagnosed as WAF).** Three separate contract bugs:
   - Brackets in the query string must be percent-encoded. Literal `availabilitySearches[0]...`
     returns HTTP 400. Use `urllib.parse.urlencode(..., quote_via=quote, safe="")`.
   - Field order must match the `#airAvailabilityRQ` DOM order. Reordering yields 400.
   - `layerAvailabilityList` requires a completed NetFunnel handshake. Without the
     `NetFunnel_ID` cookie the app answers `403` with a *soft* "세션만료" (session expired) page
     that looks like a WAF block but is 1224 bytes of application HTML, not EdgeSuite.

## Working Request Chain (11 requests)

```
1  GET  https://www.twayair.com/                      301 (sets bm_so)
2  GET  https://www.trinityairways.com/               200  3927 B
3  GET  /app/main                                     200  2616 B  challenge (sec-if-cpt)
4  GET  <collector ?t=...>                            200  528 KB  sensor script
5  POST <collector ?t=...>                            200  bm_sc -> 4~1~...  (IV8)
6  GET  /app/main                                     200  1.0 MB  trusted, has _csrf
7  GET  /ajax/booking/chkSaleRoute?<form>             200  141 B   {"success":true}
8  POST /app/booking/chooseItinerary  <form>          200  1.0 MB
9  GET  https://csnf.trinityairways.com/ts.wseq  5101 200  ticket
10 GET  https://csnf.trinityairways.com/ts.wseq  5004 200  complete
11 POST /app/booking/layerAvailabilityList            200  330 KB  flight fares
```

NetFunnel must sit **between** `chooseItinerary` and `layerAvailabilityList`. Earlier attempts
put it before `/app/main`; that ordering is wrong and does not satisfy the layer endpoint.

## Key Implementation Details

- `PROFILE = firefox135`, UA = Firefox 135. Chrome impersonation works at the document level but
  the sensor replay was validated only on Firefox. Keep Firefox.
- `_is_challenge()` must test `sec-if-cpt` **and** absence of `name="_csrf"`. The trusted 1 MB
  page also contains `bazadebezolkohpepadr`, so that token alone gives false positives.
- IV8 `environment["location"]["href"]` must be the **page** URL (`/app/main`), not the collector
  script URL, or relative sensor POSTs resolve to the wrong host and the page stays gated.
- IV8 bridge must expose `responseURL` (the challenge script inspects it to decide whether to
  reload) and must write `Set-Cookie` values back into `document.cookie`.
- The sensor bridge must seed every cookie in the jar, HttpOnly included.
- `bm_sc` grade progression observed: `1~1~` -> `2~1~` (challenge solved, app still soft-403) ->
  `4~1~` (trusted, business paths open).

## Form Contract (must reproduce exactly)

```
_csrf
searchDate=MMDD
promoCode=            (browser sent OCT26; not required)
cmpIndDiv=            (browser sent I; not required)
defaultPromoCode=
bookingTicket=
tripType=OW
bookingType=HI
promoCodeDetails.promoCode=
validPromoCode=
availabilitySearches[0..4].depAirport      (index 0 = route, rest empty)
availabilitySearches[0..4].arrAirport
availabilitySearches[0..4].flightDate
paxCountDetails[0..2].paxCount              (1,0,0)
availabilitySearches[0..4].depAirportName   (Korean, e.g. 인천)
availabilitySearches[0..4].arrAirportName   (Korean, e.g. 오사카)
gaLocation=메인
pax=1&pax=0&pax=0
deptAirportCode / arriAirportCode / schedule
```

`layerAvailabilityList` body: `_csrf, pos=KR, currency=KRW, gaLocation=메인, cmpIndDiv=I`.

## Project Files

- `main.py` — the collector. `FlightCollector.build_form_fields()` owns the form contract,
  `_parse_availability()` the fare parser, `run_collector()` the IV8 sensor stage.
- `utils/iv8_silent.py`, `utils/logger.py`
- `tests/test_availability.py` — 2 offline parser tests, passing.
- `js_reverse_cache/akamai/` — captured landing, challenge, collector, pixel, trusted page.
- `分析报告.md` — analysis notes.

## Commands

```powershell
python -m unittest tests.test_availability -v
python main.py --date 2026-10-31 --departure ICN --arrival KIX
python main.py --date 2026-11-14 --departure ICN --arrival NRT
```

## Constraints Still In Force

- Read-only. No booking, seat hold, or payment steps.
- `AKAMAI_MAX_TOTAL_REQUESTS=100`; a successful run uses 11.
- Never persist raw Cookie, NetFunnel ticket, sensor body, CSRF token, or form payload. Logging
  keeps status, redacted path, byte counts, and cookie names/lengths only.
- Collector URL path and `?t=` rotate per session. Never hardcode them.
