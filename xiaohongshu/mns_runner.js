'use strict';

/*
 * 小红书 mnsv2 纯 VM 黑盒运行器
 *
 * 原理：assets/mnsvm.js 里是一段 JSVMP（解释器 + __$c 字节码）。
 *   - 顶层程序会定义一堆函数并把其中一个 mnsv2 挂到 globalThis；
 *   - 但顶层分支依赖浏览器环境，Node 里不一定走到挂载那一步；
 *   - 因此这里不依赖 window.mnsv2，而是直接调用解释器入口 _0x31ad27，
 *     对字节码里 mnsv2 那段 (start=27188, len=26) 求值。
 *   - mnsv2 的闭包环境就是 VM 自己的作用域链，用顶层函数携带的常量/函数池
 *     拼出等价的 env 包装对象喂进去。
 *
 * 输入(stdin JSON): { c, u, p, bc, cookie, webSsk, storage? }
 * 输出(stdout JSON): { x3 } 或 { error }
 */

const fs = require('fs');
const path = require('path');

const MNS_START = 27188; // __$c 里 mnsv2 字节码起始偏移
const MNS_LEN = 26;      // mnsv2 字节码长度
const POOL_SRC_START = 12780; // 顶层函数 _0xb980 的 start，用它取常量/函数池

function main(input) {
  let code = fs.readFileSync(path.join(__dirname, 'assets', 'mnsvm.js'), 'utf8');

  // 在 funcdef 处理点注入：记录每个函数定义区间，并把解释器入口暴露出来
  const anchor = '_0x425731=_0x4d21fc[_0x5edc27(0x79)](_0x254e53,_0x30754b,_0x415185);';
  code = code.split(anchor).join(
    anchor +
    'global.__DEFS=global.__DEFS||[];' +
    'global.__DEFS.push([_0x415185+4,_0x425731-2]);' +
    'global.__CALL=_0x31ad27;'
  );

  const appId = input.appId || 'xhs-pc-web';
  const storage = Object.assign({}, input.storage || {});
  if (!storage.webSsk && input.webSsk) {
    storage.webSsk = JSON.stringify({ [appId]: input.webSsk });
  }

  // ---- 构造浏览器环境（只需够 VM 初始化即可）----
  // 注意：Node 自带只读的 navigator/performance 等 getter，必须用 defineProperty 覆盖。
  const define = (k, v) => {
    try {
      Object.defineProperty(global, k, { value: v, writable: true, configurable: true, enumerable: true });
    } catch (e) {
      try { global[k] = v; } catch (e2) { /* ignore */ }
    }
  };
  define('window', global);
  define('self', global);
  define('performance', {
    setupPolyfill() {}, setNavigationStart() {}, clearResourceTimings() {},
    resourcesBufferCache: [],
  });
  define('document', {
    cookie: input.cookie || '',
    defaultView: global,
    getElementById: () => null, getElementsByTagName: () => [],
    querySelector: () => null, querySelectorAll: () => [], evaluate: () => null,
    createElement: () => ({ getContext: () => null, style: {}, appendChild() {} }),
    documentElement: { style: {} }, body: { appendChild() {} },
    addEventListener() {}, removeEventListener() {},
  });
  define('navigator', {
    userAgent: input.ua || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0',
    platform: 'Win32', language: 'zh-CN', languages: ['zh-CN', 'zh'],
    webdriver: false, vendor: 'Google Inc.', appVersion: '5.0',
    hardwareConcurrency: 8, plugins: [], mimeTypes: [], deviceMemory: 8,
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

  const saved = [console.log, console.error, console.warn];
  console.log = () => {}; console.error = () => {}; console.warn = () => {};
  try { (0, eval)(code); } finally {
    console.log = saved[0]; console.error = saved[1]; console.warn = saved[2];
  }

  if (typeof global.__CALL !== 'function') throw new Error('VM 初始化失败：_0x31ad27 未暴露');

  // ---- 取常量/函数池：优先用 _0xb980 的闭包 env ----
  const K_ENV = String.fromCharCode(0x399, 0x49, 0x399); // 'ΙIΙ'
  const K_START = String.fromCharCode(0x49, 0x49, 0x399); // 'IIΙ'
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

  // ---- 拼 mnsv2 的作用域 env 包装 ----
  const $0 = [
    undefined, {}, global, undefined, global.performance, encodeURIComponent, Array, TextEncoder,
    Date, Math, Uint8Array, global.document, setTimeout, RegExp, unescape, parseInt, Object,
    global.navigator, undefined, Set, Function, String, Error, global.chrome, Event, Reflect,
  ];
  const wrapper = { 0: $0, d: 2, $2: null, $0: $0, $1: pool, length: 1 };
  wrapper.$2 = wrapper;

  let r;
  const saved2 = [console.log, console.error, console.warn];
  console.log = () => {}; console.error = () => {}; console.warn = () => {};
  try {
    r = global.__CALL(global.__$c, MNS_START, MNS_LEN, [input.c, input.u, input.p], wrapper, global, null, 0);
  } finally {
    console.log = saved2[0]; console.error = saved2[1]; console.warn = saved2[2];
  }
  const x3 = String(r);
  if (!/^mns0[0-9a-z]+_/.test(x3)) throw new Error('mnsv2 输出异常: ' + x3.slice(0, 40));
  return { x3 };
}

let raw = '';
process.stdin.on('data', (d) => { raw += d; });
process.stdin.on('end', () => {
  let out;
  try {
    out = main(JSON.parse(raw || '{}'));
  } catch (e) {
    out = { error: String(e && e.message || e) };
  }
  process.stdout.write(JSON.stringify(out));
});
