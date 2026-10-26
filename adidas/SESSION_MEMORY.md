# Adidas HK 逆向任务记忆

## 目标

站点：`https://www.adidas.com.hk/`

目标：纯协议、脱离浏览器获取 Adidas HK 商品信息。

项目目录：`D:\AAA\pythonproject\2623逆向测试\adidas`

## 商品列表接口

已确认的商品分页接口：

```text
https://www.adidas.com.hk/on/demandware.store/Sites-adidas-HK-Site/en_HK/Search-UpdateGrid
```

典型参数：

```text
cgid=men
pmin=0.01
start=144
sz=48
selectedUrl=https://www.adidas.com.hk/on/demandware.store/Sites-adidas-HK-Site/en_HK/Search-UpdateGrid?cgid=men&pmin=0.01&start=144&sz=48
```

分页规律：

```text
start=0      第1页
start=48     第2页
start=96     第3页
start=144    第4页
```

用户提供的浏览器 cURL 请求：

`D:\AAA\pythonproject\2623逆向测试\adidas\adidos.txt`

该文件包含完整请求 URL、Edge 155 UA、Client Hints、Referer、`x-requested-with: XMLHttpRequest` 和一组 Adidas/Demandware/Akamai Cookie 样本。动态 Cookie 不得作为长期固定配置。

## 商品响应样本

完整 HTML 商品列表响应：

`D:\AAA\pythonproject\2623逆向测试\adidas\sreach.html`

已确认：

- `data-page-number=4`
- UTF-8 大小约 644454 字节
- 主商品卡片 48 张
- 主商品 `data-pid` 匹配数 48

主商品卡片形态：

```html
<div class="product"
     data-pid="LG6998"
     data-product-status="IN STOCK"
     data-tracking-product-tile="...">
```

`data-tracking-product-tile` 中有结构化字段：

- `product_id`
- `product_model_id`
- `product_name`
- `product_price_type`
- `product_gender`
- `product_sport`
- `product_brand`
- `product_category`
- `product_type`
- `product_status`
- `product_price`
- `product_discount_percentage`
- `product_rating`
- `product_reviews`

HTML 还可提取：

- `.pdp-link a[href]`：商品详情链接和名称
- `.sales .value[content]`：数值价格
- `.sales .value`：格式化价格
- `.tile-image.image-default`：主图
- `.tile-image.image-alternate`：备用图
- `.product-badges-text`：商品标签
- `.gender-division`：分类文本
- `.color-attribute[data-pid]`：颜色/变体

示例商品：

```text
ID: LG6998
名称: FUTURE STYLE WOVEN JACKET
详情: /en/future-style-woven-jacket/LG6998.html
价格: 1099.0
状态: IN STOCK
```

结论：`Search-UpdateGrid` 就是商品列表业务接口，返回 HTML，不是 JSON。不要继续寻找另一个 JSON 商品列表接口。

## Akamai 状态

Akamai 已定位，但尚未确认通过。

证据：

- 首页返回 HTTP 403
- 页面提示 Adidas security issue
- 加载随机多段 challenge 脚本：

```text
/CAcWH/8AFW/UuUB/1t86/p0G/kkY7p4Ecik/YhYNBgEB/ISxaV/DUMT1AY
```

challenge 脚本缓存：

`D:\AAA\pythonproject\2623逆向测试\adidas\js_reverse_cache\akamai\challenge.js`

SHA-256：

```text
553e4f62200be416a06c91dcb9a5980c7b2be01609899c600b2dcbc3cb3713df
```

大小：521528 字节。

浏览器真实 challenge POST：

- URL：同一随机 challenge 路径
- method：POST
- Content-Type：`application/json`
- JSON 顶层字段：`body`
- 浏览器 body 长度：3176 字节
- 响应：HTTP 200
- 响应体：空
- `Server-Timing` 含 `ak_p`
- 响应更新 `bm_s`

观察到的 Akamai Cookie：

```text
_abck
bm_s
bm_sz
bm_so
bm_lso
ak_bmsc
AKA_A2
akacd_Generic_Prod_PR_CommLean
```

重要：HTTP 200 + 空响应体不等于 Akamai 通过。必须看到后续业务页面或商品接口返回内容。

## NV8 状态

NV8 根目录：`D:\develop_software\Nv8`

本地版本：0.1.0，Node 要求 >=18.18，推荐 Node 22+。

NV8 已成功做到：

- 在 Edge-like Realm 运行 Adidas challenge JS
- 使用 HTML 外链脚本执行方式保留 `document.currentScript`
- 生成 challenge POST body
- 通过 `networkRelay` 交给 Python `curl_cffi` Session
- Python relay 实际发出请求

NV8 文件：

- `js_reverse_cache/akamai/nv8_probe.mjs`
- `js_reverse_cache/akamai/relay_helper.py`
- `js_reverse_cache/akamai/nv8_probe_result.json`

当前 NV8 生成 body 约 4563 字节，和 Firefox 正样本 3176 字节不同。relay 返回 HTTP 200 空体，含 `ak_p` 和 Akamai trace，但没有形成后续业务放行。

同一出口下真实 Firefox 入口也返回 403，所以当前阻塞可能同时涉及：

- 出口信誉
- TLS/HTTP 传输一致性
- UA/Client Hints
- Edge 与 Firefox 指纹差异
- Akamai sensor body 与浏览器样本差异

不要把当前结果误报为 Akamai 已通过。

### 纯协议 Akamai 实现纠正与当前状态

`main.py` 的列表/详情接口曾经通过 `curl_cffi firefox135` 返回业务数据，但这只证明当时该业务请求可用，不代表 `main.py` 实现了 Akamai sensor 或生成 `_abck`。必须表述为：纯协议商品接口曾成功；完整 Akamai challenge/sensor 算法未完成。

用户批准隔离 NV8 执行当前轮换 challenge，限 Adidas HK，Cookie 仅记录名称/长度/哈希前缀。本轮 4-request 上限内的结果：

- 首页 `403`，同一 Python Session 收到服务器发出的 `_abck`、`bm_s`、`bm_so`、`bm_sz` 等 Cookie。
- 当前脚本 hash：`9da6548845f42c921baaa9a6722b6eef119953fe171ec411baf2ef51ed4148e4`。
- NV8 生成一个 sensor POST，body 长度 `3843`，但状态是 `replay-miss:missing`；Python Session broker 收到 `0` 次请求。
- 后续商品列表 `200`/48 条，但因为 sensor 没经 broker 发出，不作为 Akamai 算法通过证据。
- 本轮总 HTTP 请求没有超过批准的 4 次上限；不保存 Cookie 原值。

新建/修改的调试辅助：

- `js_reverse_cache/akamai/run_same_session.py`
- `js_reverse_cache/akamai/run_current_challenge.mjs`
- `js_reverse_cache/akamai/relay_helper.py`
- `js_reverse_cache/akamai/test_relay_offline.py`

离线 loopback broker 假响应测试通过。剩余阻塞：NV8 networkRelay 子进程没有连到 Python-owned broker，NV8 fail-open 到空 replay。修复 live bridge 并取得完整同轮 Cookie transition 与商品业务响应之前，不得声称 Akamai sensor 算法已完成。

### 2026-10-24 Firefox 135 对齐结果

使用托管 Camoufox Firefox 135 在同一出口重新验证：

- 首页首次 `403`，随机 challenge GET 后 POST 同一路径，POST `200` 空体，body `3171` 字节，含 `ak_p` 和 `x-akamai-trace-id`。
- challenge 后直接访问 `Search-UpdateGrid` 得到 `200 text/html`，页面含 48 条商品。
- 浏览器 UA：Firefox 135 / Windows，`x-firefox-spdy: h2`，时区 `Asia/Shanghai`。
- 关键 Cookie 均由 HTTP `Set-Cookie` 产生，未发现 JS 写 Cookie；包含 `_abck`、`bm_s`、`bm_sz`、`bm_so`、`ak_bmsc`、`akacd_Generic_Prod_PR_CommLean`。
- Python 改用 `curl_cffi impersonate=firefox135`，同步 Firefox 135 UA、`en-US,en;q=0.5`、`gzip, deflate, br, zstd` 和 `Upgrade-Insecure-Requests` 后，连续两次单页均 `200` 业务 HTML。
- Python 两页验证：page `1/2`，商品 `96`，唯一 ID `96`。

结论：当前不需要另外提供 TLS 参数；已有 curl_cffi Firefox 135 impersonation 足够完成当前出口的业务请求。若后续出现浏览器和 Python 同时被拒绝，优先换出口；若浏览器成功而 Python 失败，再继续比对 HTTP/2、请求时序和 Cookie 发送边界。

## 现有项目文件

根目录：

- `main.py`：Python 商品 HTML 解析和分页请求入口，默认使用 `firefox135` impersonation，会返回商品字段、分页状态及 status/content_type/body_length/challenge/business_page/cookie_names。
- `requirements.txt`
- `.gitignore`
- `分析报告.md`
- `adidos.txt`
- `sreach.html`
- `SESSION_MEMORY.md`

Akamai 缓存目录：

- `js_reverse_cache/akamai/challenge.js`
- `js_reverse_cache/akamai/baseline.md`
- `js_reverse_cache/akamai/challenge_request.json`
- `js_reverse_cache/akamai/entry_403.html`
- `js_reverse_cache/akamai/nv8_probe.mjs`
- `js_reverse_cache/akamai/nv8_probe_result.json`
- `js_reverse_cache/akamai/relay_helper.py`

## 下一步

离线解析器和单页请求骨架已完成；下一步继续解决 live Akamai 状态：

1. 用可接受 Adidas 入口的当前会话/出口请求一页，检查：
   - HTTP 状态
   - 响应长度
   - `.product` 数量
   - 是否返回 403 challenge
   - 是否返回业务 HTML
2. live 成功后再扩展多页和去重。
3. 商品去重字段优先使用 `product_id` / `data-pid`。
4. 当前离线验收结果：`page_number=4`、`products=48`、`unique_ids=48`、`color_variants=82`。
5. 当前 live 结果：对齐 Firefox 135 后，单页连续两次和两页分页均为业务 `200 text/html`；后续继续验证更长分页范围和状态刷新。

### 商品详情接口已确认

列表页不是最终详情。当前商品详情使用同一会话调用：

```text
Globale-Cache?remoteIncludeUrl=Product-ShowQuickView&pid=<PRODUCT_ID>&ajax=true
```

直接 `/en/<slug>/<pid>.html` 可能返回 403，`Product-Variation` 也可能需要具体尺码参数；Quick View 返回 `200 text/plain;charset=UTF-8`，正文是 JSON，`product` 对象含详情字段。

`main.py` 已新增：

- `build_quickview_url`
- `parse_product_detail`
- `fetch_product_detail`
- `collect_product_details`
- CLI 参数 `--product ID` / `--products ID1,ID2`

详情验收：

- `KH6728`：17 个尺码，13 个 selectable，颜色库存 3 个，短描述和 6 条 bullets。
- `KK0633`：HTTP 200，17 个尺码。
- `KS7400`：HTTP 200，8 个尺码。

### Akamai 纯协议复核及 relay 状态

- `main.py` 只用 curl_cffi firefox135 请求商品接口；此前商品数据成功不能证明程序实现了 sensor 或 `_abck` 算法。
- 首个 sensor relay 轮次曾 fail-open 到 `replay-miss:missing`。离线 mock 定位 Windows helper 路径错误；使用 `fileURLToPath()` 和显式 loopback port 后，NV8→Python broker mock 通过，outcome=`service-worker`、响应 `relay-ok`。离线测试：`test_nv8_relay_offline.mjs`、`test_relay_offline.py`。
- 用户批准额外最多 12 次请求。修复后的集成 `main.py --akamai-protocol` 实际用 5 次：home 403 → 当轮 challenge JS → 一个 sensor POST relay 200/空体/`ak_p` → Search-UpdateGrid 200/48 个商品 → 同 Session Quick View 200 且 product ID 匹配。
- 当轮 challenge SHA-256：`f4f6388954c14cc96a7c9c0562c65bda8c4a06b012ec55ac4ca44c970eca6e17`；sensor body `4560` 字节。Cookie 原值不落盘，只记录 name/length/hash 前缀。
- 新入口：`python main.py --akamai-protocol`。NV8 在隔离 Realm 执行当轮 challenge JS；Python 单 Session 负责所有 live HTTP。
- 当前可声称 browser-free 当前 challenge 执行与商品读取链路通过；不声称通用手写/数学还原 `_abck` 算法。脚本每个 session 轮换；后续多阶段挑战需要新一轮验证与预算。
