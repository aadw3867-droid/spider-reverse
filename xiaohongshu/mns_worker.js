'use strict';

/*
 * 小红书 mnsv2 常驻 worker（高并发用）
 *
 * 与 mns_runner.js 的区别：mns_runner 每次签名都新起进程、重载 288KB VM；
 * 本 worker 进程内只加载/初始化一次 VM，之后每行输入只是一次纯函数调用。
 *
 * 协议（换行分隔的 JSON）：
 *   输入一行: { c, u, p, bc, cookie, webSsk, appId?, ua?, storage? }
 *   输出一行: { x3 } 或 { error }
 *
 * 若某行里的 bc/cookie/webSsk/appId/ua 与当前已初始化的不同，会自动重建 VM
 * （同账号/设备连续签名时不会重建）。
 */

const fs = require('fs');
const path = require('path');

const MNS_START = 27188;
const MNS_LEN = 26;
const POOL_SRC_START = 12780;

const ANCHOR = '_0x425731=_0x4d21fc[_0x5edc27(0x79)](_0x254e53,_0x30754b,_0x415185);';
const RAW = fs.readFileSync(path.join(__dirname, 'assets', 'mnsvm.js'), 'utf8');
const CODE = RAW.split(ANCHOR).join(
  ANCHOR +
  'global.__DEFS=global.__DEFS||[];' +
  'global.__DEFS.push([_0x415185+4,_0x425731-2]);' +
  'global.__CALL=_0x31ad27;'
);

function define(k, v) {
  try {
    Object.defineProperty(global, k, { value: v, writable: true, configurable: true, enumerable: true });
  } catch (e) {
    try { global[k] = v; } catch (e2) { /* ignore */ }
  }
}

let signer = null;
let signerKey = null;

function buildSigner(input) {
  const appId = input.appId || 'xhs-pc-web';
  const storage = Object.assign({}, input.storage || {});
  if (!storage.webSsk && input.webSsk) storage.webSsk = JSON.stringify({ [appId]: input.webSsk });

  define('window', global);
  define('self', global);
  define('performance', { setupPolyfill() {}, setNavigationStart() {}, clearResourceTimings() {}, resourcesBufferCache: [] });
  define('document', {
    cookie: input.cookie || '', defaultView: global,
    getElementById: () => null, getElementsByTagName: () => [],
    querySelector: () => null, querySelectorAll: () => [], evaluate: () => null,
    createElement: () => ({ getContext: () => null, style: {}, appendChild() {} }),
    documentElement: { style: {} }, body: { appendChild() {} },
    addEventListener() {}, removeEventListener() {},
  });
  define('navigator', {
    userAgent: input.ua || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0',
    platform: 'Win32', language: 'zh-CN', languages: ['zh-CN', 'zh'],
    webdriver: false, vendor: 'Google Inc.', appVersion: '5.0', hardwareConcurrency: 8,
    plugins: [], mimeTypes: [], deviceMemory: 8,
  });
  define('chrome', { runtime: {}, app: {} });
  define('screen', { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24, pixelDepth: 24 });
  define('outerWidth', 1920); define('outerHeight', 1080); define('innerWidth', 1920); define('innerHeight', 969);
  define('location', {
    href: 'https://www.xiaohongshu.com/explore', origin: 'https://www.xiaohongshu.com',
    protocol: 'https:', host: 'www.xiaohongshu.com', hostname: 'www.xiaohongshu.com',
    pathname: '/explore', search: '', hash: '',
  });
  define('__bc', input.bc || '');
  const ls = {
    getItem(k) { return Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null; },
    setItem(k, v) { storage[k] = String(v); },
    removeItem(k) { delete storage[k]; },
  };
  define('localStorage', ls);
  define('sessionStorage', ls);
  define('HTMLElement', class {});
  define('addEventListener', () => {});
  define('removeEventListener', () => {});

  global.__DEFS = [];
  const saved = [console.log, console.error, console.warn];
  console.log = () => {}; console.error = () => {}; console.warn = () => {};
  try { (0, eval)(CODE); } finally {
    console.log = saved[0]; console.error = saved[1]; console.warn = saved[2];
  }
  if (typeof global.__CALL !== 'function') throw new Error('VM 初始化失败');

  const K_ENV = String.fromCharCode(0x399, 0x49, 0x399);
  const K_START = String.fromCharCode(0x49, 0x49, 0x399);
  const names = Object.getOwnPropertyNames(global).filter((k) => /^_[0-9a-f]{32}$/.test(k));
  let pool = null;
  for (const k of names) {
    const f = global[k];
    if (typeof f === 'function' && f[K_START] === POOL_SRC_START) { pool = f[K_ENV]; break; }
  }
  if (!pool) {
    for (const k of names) {
      const f = global[k];
      if (typeof f === 'function' && f[K_ENV]) { pool = f[K_ENV]; break; }
    }
  }
  if (!pool) throw new Error('找不到常量/函数池');

  const $0 = [
    undefined, {}, global, undefined, global.performance, encodeURIComponent, Array, TextEncoder,
    Date, Math, Uint8Array, global.document, setTimeout, RegExp, unescape, parseInt, Object,
    global.navigator, undefined, Set, Function, String, Error, global.chrome, Event, Reflect,
  ];
  const wrapper = { 0: $0, d: 2, $2: null, $0: $0, $1: pool, length: 1 };
  wrapper.$2 = wrapper;

  return function (c, u, p) {
    let r;
    const sv = [console.log, console.error, console.warn];
    console.log = () => {}; console.error = () => {}; console.warn = () => {};
    try {
      r = global.__CALL(global.__$c, MNS_START, MNS_LEN, [c, u, p], wrapper, global, null, 0);
    } finally {
      console.log = sv[0]; console.error = sv[1]; console.warn = sv[2];
    }
    return String(r);
  };
}

function configKey(input) {
  return JSON.stringify([input.bc || '', input.cookie || '', input.webSsk || '', input.appId || 'xhs-pc-web', input.ua || '']);
}

function handleLine(line) {
  let out;
  try {
    const req = JSON.parse(line);
    const key = configKey(req);
    if (!signer || key !== signerKey) {
      signer = buildSigner(req);
      signerKey = key;
    }
    const x3 = signer(req.c, req.u, req.p);
    if (!/^mns0[0-9a-z]+_/.test(x3)) throw new Error('mnsv2 输出异常: ' + x3.slice(0, 40));
    out = { x3 };
  } catch (e) {
    out = { error: String(e && e.message || e) };
  }
  process.stdout.write(JSON.stringify(out) + '\n');
}

process.stdin.setEncoding('utf8');
let buf = '';
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (line) handleLine(line);
  }
});
