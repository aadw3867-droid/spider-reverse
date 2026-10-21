# 抖音主页视频列表爬取（传统补环境方案）

用**传统补环境**的方式逆向抖音主页接口 `/aweme/v1/web/aweme/post/`，
在纯 Node 里手工补齐浏览器环境，让两套 SDK 在本地跑通：

- **BDMS**（`bdms_1.0.1.19_fix.js`）生成 `a_bogus`
- **secsdk**（`secsdk_runtime_bundler_34.js`）生成 `x-secsdk-web-signature`

`node` 负责生成两个签名，`python` 负责组装参数并真实发包。

## 目录结构

```
补环境(env)
├── bdms_1.0.1.19_fix.js          # BDMS SDK（a_bogus 算法），公开 CDN 冻结资产
├── secsdk_runtime_bundler_34.js  # secsdk 运行时（webSignUrl / x-secsdk-web-signature）
├── env.js                         # 传统补环境：手工构建 window/document/navigator/...
├── sign.js                        # Node 侧：两段式签名（Stage A + Stage B）
└── main.py                        # Python 发包侧：调用 Node 签名 + curl_cffi 请求
```

## 依赖

- Python >= 3.9，安装 `curl_cffi`（用于 Chrome TLS 指纹伪装）
- Node >= 18（无第三方依赖，纯 `vm` + 手工补环境）

## 使用方法

1. 打开一次抖音主页（`https://www.douyin.com/user/<sec_user_id>`），在 DevTools 里抓取会话状态：
   - Cookie：`UIFID`、`s_v_web_id`、`ttwid`、`odin_tt`（可选 `__ac_nonce` / `__ac_signature`）
   - `localStorage` 的 `xmst`（即请求里的 `msToken`）

2. 把上面的值填入 `main.py` 顶部的 `CONFIG` 字典。

3. 运行：

```powershell
python main.py
```

## 签名链路（与真实浏览器一致）

```
stage1 URL（基础参数 + msToken）
  └─ Stage A (BDMS)：window.bdms.init() 后，fetch(stage1Url) 被拦截并追加 &a_bogus=...
  └─ Stage B (secsdk)：window.use('webSignUrl')(stage1 + verifyFp/fp)
        -> 追加 &uifid=<UIFID cookie>&timestamp=<签名时刻>&x-secsdk-web-signature=<hex>
  └─ 用最终 URL 真实发包
```

## 关键点 / 易错点

1. **UA 必须一致**：`env.js` 里签名环境的 UA 与 `main.py` 发包 UA 必须完全一致，
   否则可能返回 200 但 body 为空。
2. **`webSignUrl` 输入契约**：调用 `webSignUrl` 前的 URL 不能带 `uifid` / `timestamp`，
   否则会出现 `Validate Error`（服务端比对签名内 timestamp 与 URL timestamp）。
3. **`msToken` 会过期**：`xmst` 过期后需要刷新，参考端点：
   `https://mssdk.bytedance.com/web/r/token?ms_appid=6383&msToken=<旧 token>`。
4. **两个 SDK 都不能做纯 Python 算法还原**：二者都是环境驱动的 JSVMP / 安全 SDK，
   必须在忠实的 JS 运行时里执行（这里用 Node + 手工补环境）。
5. **SDK 版本升级即失效**：`bdms_*.js` / `runtime_bundler_*.js` 一旦版本升级，
   需要重新抓取对应资产并刷新本工程。

## 错误矩阵

| HTTP | 原因 |
|------|------|
| 403 `Signature Not Found` | 缺少 `x-secsdk-web-signature` |
| 403 `Uifid Not Found` | 缺少 `uifid` 或 `UIFID` cookie |
| 403 `Sign Invalid` | `a_bogus` 或 secsdk 签名被拒 |
| 403 `Validate Error` | URL 的 `timestamp` 与签名内 timestamp 不一致 |
| 200 空 body | 签名环境 UA 与发包 UA 不一致 |
