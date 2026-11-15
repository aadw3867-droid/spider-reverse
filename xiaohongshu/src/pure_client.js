'use strict';
/**
 * 小红书纯算客户端（不加载 VM，不依赖 Python）
 *
 * 链路：mns0201_pure.sign() -> x3(mns0201_...) -> XYS_ 容器 -> HTTP
 * 依赖：Node >= 18（内置 fetch / crypto），assets/config.json
 */
const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const { sign: pureSign } = require('./mns0201_pure.js');

const ROOT = path.join(__dirname, '..');
const BASE = 'https://edith.xiaohongshu.com';
const STD = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const CUS = 'ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5';
const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0';

const DEFAULT_BODY = {
  cursor_score: '', num: 20, refresh_type: 3, note_index: 6,
  unread_begin_note_id: '', unread_end_note_id: '', unread_note_count: 0,
  category: 'homefeed_recommend', search_key: '', need_num: 8,
  image_formats: ['jpg', 'webp', 'avif'], need_filter_image: false,
};

const sha1 = (b) => crypto.createHash('sha1').update(b).digest();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadConfig() {
  const p = path.join(ROOT, 'assets', 'config.json');
  if (!fs.existsSync(p)) throw new Error('缺少 assets/config.json');
  const cfg = JSON.parse(fs.readFileSync(p, 'utf8'));
  if (!cfg.cookie) throw new Error('config.json 缺少 cookie');
  if (!cfg.webSsk) throw new Error('config.json 缺少 webSsk');
  return cfg;
}

function a1FromCookie(ck) {
  const m = (ck || '').match(/(?:^|;\s*)a1=([^;]+)/);
  return m ? m[1] : '';
}

function customB64(buf) {
  const s = buf.toString('base64');
  let out = '';
  for (const ch of s) { const i = STD.indexOf(ch); out += i >= 0 ? CUS[i] : ch; }
  return out;
}

function buildX6X7(webSsk, u) {
  const nonce = crypto.randomBytes(4);
  const ssk = Buffer.from(webSsk, 'base64');
  const s = Buffer.concat([nonce, sha1(Buffer.concat([ssk, nonce]))]);
  const x7 = s.toString('base64');
  const x6 = sha1(Buffer.concat([Buffer.from(u, 'hex'), s])).toString('base64');
  return { x6, x7 };
}

/** 生成一份完整请求头（x-s 为 XYS_ 容器，x3 为纯算 mnsv2） */
function makeSigned(cfg, apiPath, bodyStr, opts) {
  opts = opts || {};
  const nowMs = opts.nowMs == null ? Date.now() : opts.nowMs;
  const randomU32 = opts.randomU32 == null ? crypto.randomBytes(4).readUInt32LE(0) : (opts.randomU32 >>> 0);
  const r = pureSign({
    pathname: apiPath,
    body: bodyStr,
    a1: a1FromCookie(cfg.cookie),
    loadTs: opts.loadTs == null ? 807840488 : opts.loadTs,
    windowCount: opts.windowCount == null ? 193 : opts.windowCount,
    vmStateCount: opts.vmStateCount == null ? 0 : opts.vmStateCount,
    nowMs,
    randomU32,
  });
  const { x6, x7 } = buildX6X7(cfg.webSsk, r.u);
  const payload = {
    x0: cfg.version || '4.4.3',
    x1: cfg.appId || 'xhs-pc-web',
    x2: 'Windows',
    x3: r.xs,
    x4: 'object',
    x5: r.u,
    x6: { [cfg.appId || 'xhs-pc-web']: x6 },
    x7: { [cfg.appId || 'xhs-pc-web']: x7 },
  };
  const xs = 'XYS_' + customB64(Buffer.from(JSON.stringify(payload), 'utf8'));
  const headers = {
    'content-type': 'application/json;charset=UTF-8',
    'x-s': xs,
    'x-t': String(nowMs),
    'x-s-common': cfg.xsCommon || '',
    'cookie': cfg.cookie,
    'user-agent': cfg.ua || DEFAULT_UA,
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'zh-CN,zh;q=0.9',
    'origin': 'https://www.xiaohongshu.com',
    'referer': 'https://www.xiaohongshu.com/',
  };
  return { headers, bodyStr, x3: r.xs, u: r.u, p: r.p, mask: r.mask, nowMs, randomU32 };
}

/** 单次请求（每次都用新的 nowMs / randomU32 重新签名） */
async function requestOnce(cfg, apiPath, bodyStr, opts) {
  opts = opts || {};
  const method = (opts.method || 'POST').toUpperCase();
  const s = makeSigned(cfg, apiPath, bodyStr, opts);
  const init = { method, headers: s.headers };
  if (method !== 'GET' && method !== 'HEAD') init.body = bodyStr;
  const t0 = Date.now();
  const resp = await fetch(BASE + apiPath, init);
  const text = await resp.text();
  let j = null;
  try { j = JSON.parse(text); } catch (_) { j = null; }
  const data = (j && j.data) || {};
  const save = String(opts.save || 'data').toLowerCase();
  const rec = {
    status: resp.status,
    code: j ? j.code : null,
    msg: j ? j.msg : null,
    items: Array.isArray(data.items) ? data.items.length : 0,
    cursor: data.cursor_score == null ? null : data.cursor_score,
    bytes: text.length,
    ms: Date.now() - t0,
    x3: s.x3,
    u: s.u,
    mask: s.mask,
    nowMs: s.nowMs,
    http_bad: resp.status !== 200,
  };
  if (save === 'data' || save === 'all' || save === 'full') {
    rec.data = j ? (j.data === undefined ? null : j.data) : null;
  }
  if (save === 'full' || save === 'all') rec.raw = j;
  return rec;
}

function parseArgs(argv) {
  const a = {
    count: 10, interval: 1000, api: '/api/sns/web/v1/homefeed', method: 'POST',
    body: null, query: '', out: 'out.json', retries: 1, cooldown: 65000,
    concurrency: 5, qps: 5, loadTs: 807840488, windowCount: 193, vmStateCount: 0,
    save: 'data',
  };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i], v = argv[i + 1];
    switch (k) {
      case '--count': a.count = Number(v); i++; break;
      case '--interval': a.interval = Number(v); i++; break;
      case '--api': a.api = v; i++; break;
      case '--method': a.method = v.toUpperCase(); i++; break;
      case '--body': a.body = v; i++; break;
      case '--query': a.query = v; i++; break;
      case '--out': a.out = v; i++; break;
      case '--retries': a.retries = Number(v); i++; break;
      case '--cooldown': a.cooldown = Number(v); i++; break;
      case '--concurrency': a.concurrency = Math.max(1, Number(v)); i++; break;
      case '--qps': a.qps = Math.max(0.1, Number(v)); i++; break;
      case '--loadts': a.loadTs = Number(v); i++; break;
      case '--win': a.windowCount = Number(v); i++; break;
      case '--vmstate': a.vmStateCount = Number(v); i++; break;
      case '--save': a.save = String(v).toLowerCase(); i++; break;
      case '--meta': a.save = 'meta'; break;
      case '--full': a.save = 'full'; break;
      case '--help': case '-h': a.help = true; break;
      default: if (k.startsWith('--')) throw new Error('未知参数 ' + k);
    }
  }
  return a;
}

function resolveBody(a) {
  let bodyStr = '';
  if (a.method === 'GET') {
    bodyStr = a.query ? (a.query.startsWith('?') ? a.query : '?' + a.query) : '';
    if (a.query && !a.query.startsWith('?')) a.api = a.api; // query 只进签名
    return { bodyStr, url: a.api + bodyStr };
  }
  if (a.body == null) bodyStr = JSON.stringify(DEFAULT_BODY);
  else if (a.body.startsWith('@')) bodyStr = fs.readFileSync(path.resolve(ROOT, a.body.slice(1)), 'utf8').trim();
  else bodyStr = a.body;
  return { bodyStr, url: a.api };
}

function summarize(a, results, startedAt) {
  const done = results.filter(Boolean);
  const http = {};
  for (const r of done) http[r.status] = (http[r.status] || 0) + 1;
  const ok = done.filter((r) => r.status === 200 && r.code === 0).length;
  const avg = done.length ? Math.round(done.reduce((s, r) => s + r.ms, 0) / done.length) : 0;
  return {
    mode: a.mode,
    api: a.api,
    method: a.method,
    count: a.count,
    concurrency: a.mode === 'concurrent' ? a.concurrency : 1,
    qps: a.mode === 'concurrent' ? a.qps : (a.interval ? 1000 / a.interval : 0),
    startedAt,
    endedAt: new Date().toISOString(),
    env: { loadTs: a.loadTs, windowCount: a.windowCount, vmStateCount: a.vmStateCount },
    summary: {
      total: a.count,
      done: done.length,
      ok,
      fail: done.length - ok,
      http,
      avgMs: avg,
    },
    results: done,
  };
}

function writeOut(file, doc) {
  const p = path.resolve(ROOT, file);
  const tmp = p + '.tmp';
  const ans = fs.writeFileSync(tmp, JSON.stringify(doc, null, 2), 'utf8');
  try {
    fs.renameSync(tmp, p);
  } catch (_) {
    fs.copyFileSync(tmp, p);
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
  }
  return p;
}

async function cooldownWait(ms, label) {
  const end = Date.now() + ms;
  let last = 0;
  while (Date.now() < end) {
    const left = end - Date.now();
    if (Date.now() - last >= 10000) {
      console.log(`  ${label || '冷却'}中，剩余 ${Math.ceil(left / 1000)}s`);
      last = Date.now();
    }
    await sleep(Math.min(10000, left));
  }
}

module.exports = {
  BASE, DEFAULT_BODY, loadConfig, makeSigned, requestOnce, parseArgs,
  resolveBody, summarize, writeOut, cooldownWait, sleep,
};
