/**
 * env.js — 抖音 Web 传统补环境（浏览器环境模拟）
 *
 * 在纯 Node 里手工补齐 window / document / navigator / location / screen /
 * history / localStorage / sessionStorage / XMLHttpRequest / fetch / canvas /
 * performance / crypto 等浏览器对象，让 bdms(生成 a_bogus) 与
 * secsdk(生成 x-secsdk-web-signature) 两套 SDK 能直接在本地跑通。
 *
 * 说明：这里采用“直接把全局对象挂到 globalThis 上”的传统补环境方式，
 * 不使用 jsdom / nv8 / 补环境框架。
 */

'use strict';

// ---------- 基础引用 ----------
const crypto = require('crypto');

// ---------- 通用小工具 ----------
function defineNative(obj, name, value, opts) {
  const o = opts || {};
  Object.defineProperty(obj, name, {
    value,
    writable: o.writable !== undefined ? o.writable : true,
    enumerable: o.enumerable !== undefined ? o.enumerable : false,
    configurable: o.configurable !== undefined ? o.configurable : true,
  });
  return value;
}

// 让手写函数 toString 看起来像原生
function nativeFunction(fn, name) {
  defineNative(fn, 'toString', function () {
    return 'function ' + name + '() { [native code] }';
  });
  return fn;
}

// ---------- Storage ----------
class Storage {
  constructor() {
    this._data = {};
  }
  getItem(key) {
    return Object.prototype.hasOwnProperty.call(this._data, key) ? this._data[key] : null;
  }
  setItem(key, value) {
    this._data[String(key)] = String(value);
  }
  removeItem(key) {
    delete this._data[String(key)];
  }
  clear() {
    this._data = {};
  }
  key(i) {
    const keys = Object.keys(this._data);
    return i >= 0 && i < keys.length ? keys[i] : null;
  }
  get length() {
    return Object.keys(this._data).length;
  }
}

// ---------- Element / Node 最小实现 ----------
class NodeImpl {
  constructor() {
    this.children = [];
    this.style = {};
    this.attributes = {};
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i >= 0) this.children.splice(i, 1);
    return c;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return (k in this.attributes) ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  set innerHTML(v) { this._innerHTML = v; }
  get innerHTML() { return this._innerHTML || ''; }
}

class ElementImpl extends NodeImpl {
  constructor(tagName) {
    super();
    this.tagName = (tagName || 'div').toUpperCase();
    this.nodeName = this.tagName;
    this.nodeType = 1;
    this.id = '';
    this.className = '';
  }
  get textContent() { return ''; }
  set textContent(v) {}
  get innerText() { return ''; }
  set innerText(v) {}
}

class HTMLCanvasElement extends ElementImpl {
  constructor() {
    super('canvas');
    this.width = 300;
    this.height = 150;
  }
  getContext(type) {
    if (type === '2d') return createCanvas2dContext();
    if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return createWebGLContext();
    return null;
  }
  toDataURL() { return 'data:image/png;base64,'; }
}

// ---------- Canvas 2D / WebGL 指纹（尽量模拟真实浏览器行为） ----------
function createCanvas2dContext() {
  const fn = (name) => nativeFunction(function () {}, name);
  return {
    fillRect: fn('fillRect'), strokeRect: fn('strokeRect'), clearRect: fn('clearRect'),
    beginPath: fn('beginPath'), closePath: fn('closePath'), moveTo: fn('moveTo'),
    lineTo: fn('lineTo'), arc: fn('arc'), fill: fn('fill'), stroke: fn('stroke'),
    fillText: fn('fillText'), strokeText: fn('strokeText'), save: fn('save'), restore: fn('restore'),
    translate: fn('translate'), scale: fn('scale'), rotate: fn('rotate'),
    setTransform: fn('setTransform'), transform: fn('transform'),
    createLinearGradient: fn('createLinearGradient'), createRadialGradient: fn('createRadialGradient'),
    createPattern: fn('createPattern'), measureText: fn('measureText'),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    putImageData: fn('putImageData'), drawImage: fn('drawImage'),
    getContextAttributes: () => ({ alpha: true }),
    get _canvas() { return this; },
  };
}

function createWebGLContext() {
  const fn = (name) => nativeFunction(function () {}, name);
  return {
    getParameter: (p) => {
      const map = {
        0x1F00: 'WebKit',           // VENDOR
        0x1F01: 'WebKit WebGL',     // RENDERER
        0x9245: 'WebGL',            // UNMASKED_VENDOR_WEBGL
        0x9246: 'ANGLE (Intel, Intel(R) UHD Graphics (0x0000A7A0) Direct3D11 vs_5_0 ps_5_0, D3D11)', // UNMASKED_RENDERER_WEBGL
        0x1F02: 'WebGL 1.0',        // VERSION
      };
      return map[p] || null;
    },
    getExtension: () => null,
    getSupportedExtensions: () => [],
    getShaderPrecisionFormat: () => ({ rangeMin: 127, rangeMax: 127, precision: 23 }),
    createBuffer: fn('createBuffer'), createTexture: fn('createTexture'), createShader: fn('createShader'),
    createProgram: fn('createProgram'), bindBuffer: fn('bindBuffer'), bufferData: fn('bufferData'),
  };
}

// ---------- Document ----------
class DocumentImpl extends NodeImpl {
  constructor() {
    super();
    this.nodeType = 9;
    this.nodeName = '#document';
    this.readyState = 'complete';
    this.visibilityState = 'visible';
    this.domain = 'www.douyin.com';
    this.referrer = 'https://www.douyin.com/';
    this.URL = 'https://www.douyin.com/';
    this.title = '';
    this.characterSet = 'UTF-8';
    this.charset = 'UTF-8';
    this._cookie = '';
    this.documentElement = new ElementImpl('html');
    this.head = new ElementImpl('head');
    this.body = new ElementImpl('body');
    this.currentScript = null;
    this._all = undefined;
  }
  get cookie() { return this._cookie; }
  set cookie(v) {
    // 简单解析：只取 name=value 部分，忽略过期时间
    const parts = String(v).split(';');
    const first = parts[0].trim();
    const eq = first.indexOf('=');
    if (eq > 0) {
      const name = first.slice(0, eq).trim();
      const value = first.slice(eq + 1).trim();
      const existing = this._cookie.split('; ').filter(Boolean);
      let found = false;
      const next = existing.map((pair) => {
        const e2 = pair.indexOf('=');
        if (e2 > 0 && pair.slice(0, e2).trim() === name) { found = true; return name + '=' + value; }
        return pair;
      });
      if (!found) next.push(name + '=' + value);
      this._cookie = next.join('; ');
    }
  }
  createElement(tag) {
    if (String(tag).toLowerCase() === 'canvas') return new HTMLCanvasElement();
    return new ElementImpl(tag);
  }
  createElementNS(ns, tag) { return this.createElement(tag); }
  createEvent(type) { return { type: type || 'Event', initEvent: function () {} }; }
  createTextNode() { return new NodeImpl(); }
  createDocumentFragment() { return new NodeImpl(); }
  getElementById() { return new ElementImpl('div'); }
  getElementsByTagName() { return []; }
  getElementsByClassName() { return []; }
  getElementsByName() { return []; }
  querySelector(sel) {
    // secsdk 用它定位自己的 script 标签并读取 project-id
    if (/security-secsdk|secsdk_runtime_bundler/.test(sel)) {
      const el = new ElementImpl('script');
      el.getAttribute = function (k) {
        if (k === 'project-id') return '34';
        return null;
      };
      el.src = 'https://lf-security.bytegoofy.com/obj/security-secsdk/runtime_bundler_34.js';
      return el;
    }
    return null;
  }
  querySelectorAll() { return []; }
  write() {}
  open() { return this; }
  close() {}
}

// ---------- Navigator ----------
function makeNavigator(ua) {
  const navigator = {
    userAgent: ua,
    platform: 'Win32',
    language: 'zh-CN',
    languages: ['zh-CN', 'zh'],
    hardwareConcurrency: 28,
    deviceMemory: 16,
    cookieEnabled: true,
    webdriver: false,
    maxTouchPoints: 0,
    vendor: 'Google Inc.',
    vendorSub: '',
    product: 'Gecko',
    productSub: '20030107',
    appName: 'Netscape',
    appCodeName: 'Mozilla',
    appVersion: '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
    onLine: true,
    doNotTrack: null,
    pdfViewerEnabled: true,
    plugins: { length: 0, item: () => null, namedItem: () => null, refresh: () => {} },
    mimeTypes: { length: 0, item: () => null, namedItem: () => null },
    sendBeacon: () => false,
    getBattery: () => Promise.resolve({ charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1, addEventListener: () => {} }),
    javaEnabled: () => false,
  };
  return navigator;
}

// ---------- Location ----------
function makeLocation(href) {
  const parsed = new URL(href);
  const loc = {
    href,
    protocol: parsed.protocol,
    host: parsed.host,
    hostname: parsed.hostname,
    port: parsed.port,
    origin: parsed.origin,
    pathname: parsed.pathname,
    search: parsed.search,
    hash: parsed.hash,
    toString: function () { return this.href; },
    assign: function () {},
    replace: function () {},
    reload: function () {},
  };
  return loc;
}

// ---------- History ----------
function makeHistory() {
  return {
    length: 1,
    state: null,
    back: () => {}, forward: () => {}, go: () => {},
    pushState: () => {}, replaceState: () => {},
  };
}

// ---------- Screen ----------
function makeScreen(w, h) {
  return {
    width: w, height: h,
    availWidth: w, availHeight: h - 40,
    colorDepth: 24, pixelDepth: 24,
    availLeft: 0, availTop: 0,
    orientation: { angle: 0, type: 'landscape-primary' },
  };
}

// ---------- Performance ----------
function makePerformance() {
  const t0 = Date.now();
  return {
    now: () => Date.now() - t0 + 0.1,
    timeOrigin: t0,
    timing: {
      navigationStart: t0, fetchStart: t0, domainLookupStart: t0, domainLookupEnd: t0,
      connectStart: t0, connectEnd: t0, requestStart: t0, responseStart: t0,
      responseEnd: t0, domLoading: t0, domInteractive: t0, domContentLoadedEventEnd: t0,
      domComplete: t0, loadEventStart: t0, loadEventEnd: t0,
    },
    getEntriesByType: () => [],
    getEntriesByName: () => [],
    mark: () => {},
    clearMarks: () => {},
    measure: () => {},
  };
}

// ---------- XMLHttpRequest ----------
function makeXMLHttpRequest() {
  function XMLHttpRequest() {
    this.readyState = 0;
    this.status = 0;
    this.responseText = '';
    this.response = '';
    this.responseType = '';
    this.onreadystatechange = null;
    this.onload = null;
    this.onerror = null;
    this._headers = {};
    this._method = 'GET';
    this._url = '';
  }
  XMLHttpRequest.prototype.open = nativeFunction(function (method, url, async) {
    this._method = method;
    this._url = url;
    this.readyState = 1;
    if (this.onreadystatechange) this.onreadystatechange();
  }, 'open');
  XMLHttpRequest.prototype.setRequestHeader = nativeFunction(function (k, v) {
    this._headers[k] = v;
  }, 'setRequestHeader');
  XMLHttpRequest.prototype.send = nativeFunction(function (body) {
    // 本环境不做真实网络请求，直接走成功回调
    this.readyState = 4;
    this.status = 200;
    this.responseText = '';
    if (this.onreadystatechange) this.onreadystatechange();
    if (this.onload) this.onload();
  }, 'send');
  XMLHttpRequest.prototype.abort = nativeFunction(function () {}, 'abort');
  XMLHttpRequest.prototype.getResponseHeader = nativeFunction(function (k) { return null; }, 'getResponseHeader');
  XMLHttpRequest.prototype.getAllResponseHeaders = nativeFunction(function () { return ''; }, 'getAllResponseHeaders');
  return XMLHttpRequest;
}

// ---------- Headers ----------
class HeadersImpl {
  constructor(init) {
    this._m = {};
    if (init && typeof init === 'object') {
      for (const k in init) this._m[k.toLowerCase()] = String(init[k]);
    }
  }
  get(k) { return this._m[String(k).toLowerCase()] || null; }
  set(k, v) { this._m[String(k).toLowerCase()] = String(v); }
  has(k) { return Object.prototype.hasOwnProperty.call(this._m, String(k).toLowerCase()); }
  append(k, v) { this._m[String(k).toLowerCase()] = String(v); }
  forEach(fn) { for (const k in this._m) fn(this._m[k], k, this); }
  keys() { return Object.keys(this._m)[Symbol.iterator](); }
  values() { return Object.values(this._m)[Symbol.iterator](); }
  entries() { return Object.entries(this._m)[Symbol.iterator](); }
}

// ---------- crypto (Web Crypto) ----------
function makeCrypto() {
  const subtle = {
    digest: (alg, data) => {
      const algo = (alg && alg.name) ? String(alg.name).toUpperCase() : 'SHA-256';
      const buf = Buffer.isBuffer(data) ? data : Buffer.from(data);
      try {
        const h = crypto.createHash(algo.toLowerCase()).update(buf).digest();
        return Promise.resolve(new Uint8Array(h));
      } catch (e) {
        return Promise.reject(e);
      }
    },
  };
  return {
    getRandomValues: (arr) => {
      const b = crypto.randomBytes(arr.length);
      for (let i = 0; i < arr.length; i++) arr[i] = b[i];
      return arr;
    },
    randomUUID: () => crypto.randomUUID(),
    subtle,
  };
}

// ---------- 主入口：构建一个干净的浏览器全局沙箱（供 vm.createContext 使用） ----------
function createEnv(cfg) {
  const c = cfg || {};
  const ua = c.ua || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36';
  const pageUrl = c.pageUrl || 'https://www.douyin.com/';
  const sw = (c.screen && c.screen.width) || 1920;
  const sh = (c.screen && c.screen.height) || 1080;

  const document = new DocumentImpl();
  const navigator = makeNavigator(ua);
  const location = makeLocation(pageUrl);
  const screen = makeScreen(sw, sh);
  const history = makeHistory();
  const performance = makePerformance();
  const localStorage = new Storage();
  const sessionStorage = new Storage();
  const cryptoObj = makeCrypto();
  const XMLHttpRequest = makeXMLHttpRequest();

  // 用一个干净对象当沙箱全局（避开 Node 25 上 globalThis 自带的 window/document 只读 getter）
  const win = {};

  win.window = win;
  win.self = win;
  win.top = win;
  win.parent = win;
  win.frames = win;
  win.globalThis = win;
  win.global = win;
  win.document = document;
  win.navigator = navigator;
  win.location = location;
  win.screen = screen;
  win.history = history;
  win.performance = performance;
  win.localStorage = localStorage;
  win.sessionStorage = sessionStorage;
  win.crypto = cryptoObj;
  win.msCrypto = cryptoObj;
  win.XMLHttpRequest = XMLHttpRequest;
  win.Headers = HeadersImpl;
  win.Storage = Storage;
  // 定时器：vm 上下文默认没有 Node 定时器，需显式传入
  win.setTimeout = setTimeout;
  win.setInterval = setInterval;
  win.clearTimeout = clearTimeout;
  win.clearInterval = clearInterval;
  win.fetch = function (input) {
    return Promise.resolve({ ok: true, status: 204, text: () => Promise.resolve(''), json: () => Promise.resolve({}) });
  };
  win.console = console;
  win.atob = (s) => Buffer.from(String(s), 'base64').toString('binary');
  win.btoa = (s) => Buffer.from(String(s), 'binary').toString('base64');
  win.URL = URL;
  win.URLSearchParams = URLSearchParams;
  win.TextEncoder = TextEncoder;
  win.TextDecoder = TextDecoder;
  win.Image = function () { this.src = ''; this.onload = null; this.onerror = null; };
  win.Event = function (type) { this.type = type; };
  win.EventTarget = function () { this.addEventListener = function () {}; this.removeEventListener = function () {}; };
  win.Node = NodeImpl;
  win.Element = ElementImpl;
  win.HTMLElement = ElementImpl;
  win.HTMLCanvasElement = HTMLCanvasElement;
  // window 常见方法
  win.addEventListener = function () {};
  win.removeEventListener = function () {};
  win.dispatchEvent = function () { return true; };
  win.requestAnimationFrame = function (cb) { return setTimeout(function () { cb(Date.now()); }, 16); };
  win.cancelAnimationFrame = function (id) { clearTimeout(id); };
  win.open = function () {};
  win.close = function () {};
  win.scrollTo = function () {};
  win.scrollBy = function () {};

  // 让 document.currentScript 在 secsdk 读取时可用
  Object.defineProperty(document, 'currentScript', {
    get() {
      return {
        src: 'https://lf-security.bytegoofy.com/obj/security-secsdk/runtime_bundler_34.js',
        getAttribute: function (k) { return k === 'project-id' ? '34' : null; },
        setAttribute: function () {},
      };
    },
    configurable: true,
  });

  // 预置 cookie / localStorage
  if (c.cookies) {
    for (const name in c.cookies) {
      document.cookie = name + '=' + c.cookies[name] + '; path=/; domain=.douyin.com';
    }
  }
  if (c.localStorage) {
    for (const k in c.localStorage) localStorage.setItem(k, c.localStorage[k]);
  }

  return {
    sandbox: win,
    window: win, document, navigator, location, screen, history, performance,
    localStorage, sessionStorage, crypto: cryptoObj, XMLHttpRequest,
  };
}

module.exports = { createEnv };
