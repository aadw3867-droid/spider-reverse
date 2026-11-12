# 小红书 x-s 纯算签名（mnsv2 独立 VM 黑盒）

不补浏览器环境、不跑无头浏览器：把页面 vendor 里的 **JSVMP（解释器 + `__$c` 字节码）** 单独抠出来，
只喂极少量运行时数据，直接对 **mnsv2 那段字节码**求值得到 `x3`，其余 `x-s` 字段用纯 Python 组装。

- 纯算，无 Selenium / Playwright / 浏览器依赖
- 常驻 Node worker 池，签名吞吐 ~ 几百次/秒，可水平扩展
- 提供 Python 封装：自动签名 + 发请求

## 原理简述

页面里存在一段 JavaScript 虚拟机（JSVMP）：`_0x1233dd(bytecode, pc, len, args, env, this, fn, mode)`
负责解释字节码。`window.mnsv2` 本身是这段 VM 的顶层程序在内部赋值的，Node 下未必走到赋值分支，
因此本库**不依赖 `window.mnsv2`**，而是：

1. `assets/mnsvm.js` 是抠出的 JSVMP（解释器 + `__$c` + 字符串表），只读；
2. 调用前在 `funcdef` 处理点注入 `global.__CALL = _0x31ad27`（解释器入口）并记录函数定义区间；
3. 取顶层函数携带的常量/函数池，拼出 mnsv2 的闭包环境；
4. 对 `start=27188, len=26` 的字节码求值 → 得到 `x3`（形如 `mns0201_...`，200 字符）。

`x-s` 组装：

```
c  = api_path + body_str
u  = md5(c)
p  = md5(api_path)
x3 = mnsv2(c, u, p)
x5 = u
x6,x7 = build_x6_x7(webSsk, u)
x-s = "XYS_" + custom_base64(JSON{x0..x7})
```

## 目录结构

```
小红书/
├─ assets/
│  ├─ mnsvm.js              # 抠出的 JSVMP（解释器 + __$c），只读
│  ├─ config.example.json   # 配置模板（占位符）
│  └─ config.json           # 本地真实配置（.gitignore，不入库）
├─ xhs/
│  ├─ __init__.py
│  ├─ crypto.py             # md5 / 自定义 base64 / x6,x7
│  ├─ mns.py                # MnsVM / MnsPool：Node worker 池（线程安全）
│  ├─ signer.py             # 组装 x-s / x-t / x-s-common
│  └─ client.py             # XhsClient：自动签名 + requests
├─ mns_runner.js            # 一次性运行器（每次起进程，便于调试）
├─ mns_worker.js            # 常驻 worker（行分隔 JSON，供线程池调用）
├─ demo.py                  # 单次示例（user/me + homefeed）
├─ demo_concurrent.py       # 并发示例 / 压测
├─ set_session.py           # 更新 cookie + webSsk 并自检
├─ requirements.txt
└─ README.md
```

## 环境要求

- Python 3.8+
- Node.js 18+（签名在 Node 里跑；可用 `XHS_NODE` 指定可执行文件路径）

## 安装

```bash
pip install -r requirements.txt
```

Windows:

```powershell
copy assets\config.example.json assets\config.json
```

macOS / Linux:

```bash
cp assets/config.example.json assets/config.json
```

## 配置 `assets/config.json`

| 字段 | 说明 | 是否账号相关 |
|------|------|--------------|
| `appId` | 默认 `xhs-pc-web` | 否 |
| `version` | 默认 `4.4.3` | 否 |
| `bc` | `globalThis.__bc`（客户端固定指纹字节码，hex，约 7558 字符） | 否（设备级） |
| `cookie` | 完整 Cookie 串（**必须含 httpOnly 的 `web_session`**；`mnsv2` 会读 `a1`/`websectiga`/`webId`） | 是 |
| `webSsk` | `localStorage.webSsk` 中 `xhs-pc-web` 的值（x6/x7 的密钥） | 是 |
| `xsCommon` | `x-s-common`（设备指纹编码，可长期复用） | 否（设备级） |

取值方式：

- `cookie`：F12 → Network → 任意 `/api/sns/web/...` 请求 → Request Headers → **整条 `Cookie`**（`web_session` 是 httpOnly，`document.cookie` 取不到）。
- `webSsk`：Console 执行 `localStorage.getItem('webSsk')`（若是 JSON 取其 `xhs-pc-web` 值）。
- 用 `set_session.py` 一次性写入并自检：

```bash
python set_session.py --cookie "a1=...; web_session=...; ..." --webssk "xxxx"
```

## 快速开始

```bash
# 单次：user/me + homefeed
python demo.py

# 并发：签名吞吐 + 并发请求（默认 user/me）
python demo_concurrent.py

# 并发打 homefeed（需登录 cookie，见“常见问题”）
python demo_concurrent.py --homefeed --req 8 --workers 4

# 只测签名吞吐
python demo_concurrent.py --sign 2000 --req 0 --workers 16
```

`demo_concurrent.py` 参数：

| 参数 | 说明 |
|------|------|
| `--sign N` | 签名基准次数（0 跳过） |
| `--req N` | 真实请求次数（0 跳过） |
| `--workers N` | 并发线程数 |
| `--homefeed` | 请求 homefeed 而非 user/me |
| `--save FILE` | 所有响应原文写入 JSON |

## 作为库使用

```python
import json
from xhs import XhsClient

cfg = json.load(open("assets/config.json", encoding="utf-8"))
client = XhsClient(cfg)

# GET
me = client.get("/api/sns/web/v2/user/me")

# POST（body 变了会自动重新签名）
resp = client.post("/api/sns/web/v1/homefeed", { ... })
print(resp.status_code, resp.json())

# 只签名不发请求
signed = client.signer.sign("/api/sns/web/v1/homefeed", body)
print(signed["x3"], signed["xs"], signed["xt"])
```

## 高并发

- 默认走**常驻 Node worker 池**（`mns_worker.js`，VM 只加载一次）。
- 池大小默认 `min(8, CPU 核数)`，可用环境变量 `XHS_MNS_WORKERS` 或 `MnsVM(pool_size=...)` 调整。
- 实测（8 worker）：纯签名 ~700–850 次/秒（全有效且互不相同）。
- 多账号：`cookie` 与 `webSsk` 按账号各自一套，各建一个池轮换；`bc` / `xsCommon` 是设备级，可长期复用；
  `x3/x5/x6/x7` 每次自动生成。

## 常见问题

**homefeed 返回 `HTTP 461`（`{"code":0,"success":true,"data":{}}`）**
通常是**游客会话**，不是签名错误：游客 cookie 时 `user/me` 返回 `guest:true`，homefeed 必 461；
换成**已登录 cookie**（`user/me` 有 `red_id`/`nickname`、无 `guest`）即可 `200 + items`，无需 `x-rap-param`。

**`找不到 mns_worker.js` / `找不到 node`**
确认在项目根目录运行；Node 不在 PATH 时设置 `XHS_NODE=C:\path\to\node.exe`。

**`config.json` 不存在**
从 `assets/config.example.json` 复制一份并填入真实值。

**cookie 过期**
重新抓取完整 Cookie + `webSsk`，用 `set_session.py` 更新。`x6/x7` 依赖 `webSsk`，`x3` 依赖 `cookie`/`bc`，过期需一并更新。

**每次 `x3` 不一样**
正常，含随机 nonce/时间戳，服务端只校验格式与可解性。

## 安全提示

- `assets/config.json`、`assets/session.txt` 含真实登录态，已加入 `.gitignore`，**不要提交**。
- 不要把 Cookie / `webSsk` / `id_token` 贴到 issue、聊天或公共仓库。

## 免责声明

本项目仅用于学习、研究与安全交流，请遵守目标网站的服务条款与当地法律法规，勿用于任何商业或非法用途。
