# Adidas Akamai Baseline

- Target: `https://www.adidas.com.hk/`
- Browser evidence: Firefox 135 via Camoufox
- Initial document: HTTP 403, `text/html`
- Challenge script: `/CAcWH/8AFW/UuUB/1t86/p0G/kkY7p4Ecik/YhYNBgEB/ISxaV/DUMT1AY`
- Challenge script SHA-256: `553e4f62200be416a06c91dcb9a5980c7b2be01609899c600b2dcbc3cb3713df`
- Challenge script size: `521528` bytes
- Challenge XHR: POST to the same random-path endpoint
- Challenge request content type: `application/json`
- Challenge request body size: `3176` bytes
- Challenge response: HTTP 200 with an empty body
- Challenge response: `Server-Timing` contains `ak_p`
- Challenge response: `cdn-cache; desc=MISS` on the POST
- Observed Akamai cookies: `_abck`, `bm_s`, `bm_sz`, `bm_so`, `bm_lso`, `ak_bmsc`

The initial 403 HTML and dynamic script are stored beside this file. Cookie values are intentionally not persisted here.
