# spider-reverse

Web 逆向学习与研究记录。所有内容仅用于技术研究与学习，请勿用于任何违反目标站点服务条款或法律法规的用途。

## 目录

| 目录 | 目标 | 关键技术 |
|---|---|---|
| `douyin/` | 抖音 | 补环境（bdms / secsdk） |
| `adidas/` | adidas 香港站 | Akamai Bot Manager sensor（NV8 执行当轮 challenge） |
| `航空机票akmi/` | T'way 机票查询 | Akamai + NetFunnel（IV8 执行 collector） |
| `re84/` | Bangkok Airways | reese84 token 续签（纯 HTTP，无浏览器） |

## 运行环境

- Python 3.10+
- 依赖：`curl_cffi`、`pycryptodome`、`beautifulsoup4`、`lxml`、`iv8`
- Node.js（`adidas/` 下的 `.mjs` 脚本）
- 外部路径通过环境变量注入，不写死在代码里：
  - `NV8_ROOT`：Nv8 运行库根目录（默认 `D:/develop_software/Nv8/src`）
  - `PYTHON`：调用谱系里使用的 Python 解释器
  - `CAMOUFOX_EXECUTABLE_PATH`：Camoufox 浏览器（仅 `re84/mint_seed.py` 首次铸种需要）

```bash
pip install curl_cffi pycryptodome beautifulsoup4 lxml iv8
```

## 快速开始

```bash
# adidas：跑当轮 challenge 并取商品列表
python adidas/main.py --pages 1

# T'way 机票可用性
python 航空机票akmi/main.py

# Bangkok Airways：无浏览器续签 reese84 token 并查询
python re84/main.py --help
```

各项目细节见其目录下的 `README.md` / `分析报告.md` / `SESSION_MEMORY.md`。

## 说明

- 仓库不含任何真实 cookie、token、账号或代理凭据；运行所需的种子需自行获取。
- 抓取到的页面脚本（`challenge.js` / `collector.js` / `netfunnel.js` 等）仅作为研究样本留档，是目标站点在特定时刻下发的公开资源。
