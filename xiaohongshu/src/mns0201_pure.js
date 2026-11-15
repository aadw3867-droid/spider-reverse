'use strict';
const crypto = require('crypto');

const T = 'MfgqrsbcyzPQRStuvC7mn501HIJBo2DEFTKdeNOwxWXYZap89+/A4UVLhijkl63G';
const XXTEA_KEY = 'e6483ca2a1eed5e3';
const DELTA = 1013904243;
const MAGIC = [121, 104, 96, 41];
const ENV_TABLE = [115, 248, 172, 102, 103, 201, 181, 131, 99, 94, 4, 68, 250, 132, 21];

const md5hex = (s) => crypto.createHash('md5').update(s, 'utf8').digest('hex');
const hexdec = (s) => Buffer.from(s, 'hex');
const u32le = (v) => { const b = Buffer.alloc(4); b.writeUInt32LE(v >>> 0); return b; };
const u64le = (v) => { const b = Buffer.alloc(8); b.writeBigUInt64LE(BigInt(v)); return b; };
const lp = (b) => Buffer.concat([Buffer.from([b.length & 255]), b]);
const xorByte = (b, s) => Buffer.from(Array.from(b, (x) => (x ^ s) & 255));

function b2w(b, appendLen) {
  const e = b.length; let a = e >> 2;
  if ((3 & e) !== 0) ++a;
  const t = new Uint32Array(appendLen ? a + 1 : a);
  if (appendLen) t[a] = e;
  for (let o = 0; o < e; ++o) t[o >> 2] |= (b[o] & 255) << ((3 & o) << 3);
  return t;
}
function w2b(v) { const o = Buffer.alloc(v.length * 4); for (let i = 0; i < v.length; i++) o.writeUInt32LE(v[i] >>> 0, i * 4); return o; }
function mx(s, y, z, p, e, k) { return ((((z >>> 5) ^ (y << 2)) + ((y >>> 3) ^ (z << 4))) ^ ((s ^ y) + (k[(p & 3) ^ e] ^ z))) >>> 0; }
function xxteaEnc(v, k) {
  const n = v.length;
  if (n < 2) return v;
  const rounds = 6 + Math.floor(52 / n);
  let s = 0, z = v[n - 1];
  for (let q = 0; q < rounds; q++) {
    s = (s + DELTA) >>> 0;
    const e = (s >>> 2) & 3;
    for (let p = 0; p < n - 1; p++) { const y = v[p + 1]; v[p] = (v[p] + mx(s, y, z, p, e, k)) >>> 0; z = v[p]; }
    const y = v[0]; v[n - 1] = (v[n - 1] + mx(s, y, z, n - 1, e, k)) >>> 0; z = v[n - 1];
  }
  return v;
}
function b64(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i] & 255, b1 = i + 1 < bytes.length ? bytes[i + 1] & 255 : 0, b2 = i + 2 < bytes.length ? bytes[i + 2] & 255 : 0;
    const n = (b0 << 16) | (b1 << 8) | b2;
    out += T[(n >>> 18) & 63] + T[(n >>> 12) & 63] + (i + 1 < bytes.length ? T[(n >>> 6) & 63] : '=') + (i + 2 < bytes.length ? T[n & 63] : '=');
  }
  return out;
}

function buildPayload({ u, p, sourceLen, a1, loadTs, vmStateCount = 0, windowCount = 184, nowMs, randomU32 }) {
  const mask = randomU32 & 255;
  const digest8 = xorByte(hexdec(u), mask).slice(0, 8);
  const helper16 = Buffer.from([1, ENV_TABLE[0] ^ mask, ...ENV_TABLE.slice(1)]);
  const tag16 = xorByte(hexdec(p), mask);
  return Buffer.concat([
    Buffer.from(MAGIC),
    u32le(randomU32),
    u64le(nowMs),
    u64le(loadTs),
    u32le(vmStateCount),
    u32le(windowCount),
    u32le(sourceLen),
    digest8,
    lp(Buffer.from(a1, 'utf8')),
    lp(Buffer.from('unk', 'utf8')),
    helper16,
    lp(Buffer.from('nop', 'utf8')),
    lp(tag16),
  ]);
}

function sign(opts) {
  const pathname = opts.pathname;
  const body = opts.body === undefined ? '' : (typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body));
  const source = pathname + body;
  const u = opts.u || md5hex(source);
  const p = opts.p || md5hex(pathname);
  const sourceLen = opts.sourceLen === undefined ? Buffer.byteLength(source) : opts.sourceLen;
  const randomU32 = opts.randomU32 === undefined ? crypto.randomBytes(4).readUInt32LE(0) : (opts.randomU32 >>> 0);
  const nowMs = opts.nowMs === undefined ? Date.now() : opts.nowMs;
  const payload = buildPayload({
    u, p, sourceLen,
    a1: opts.a1,
    loadTs: opts.loadTs,
    vmStateCount: opts.vmStateCount === undefined ? 0 : opts.vmStateCount,
    windowCount: opts.windowCount === undefined ? 184 : opts.windowCount,
    nowMs, randomU32,
  });
  const k = b2w(Buffer.from(XXTEA_KEY, 'latin1'), false);
  const enc = w2b(xxteaEnc(b2w(payload, true), k));
  return { xs: 'mns0201_' + b64(enc), payload, u, p, mask: randomU32 & 255 };
}

module.exports = { sign, buildPayload, xxteaEnc, b64, b2w, w2b, md5hex, T, ENV_TABLE };

if (require.main === module) {
  const A1 = 'A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1'; // 脱敏示例值，非真实账号
  const r = sign({
    pathname: '/api/sns/web/v1/homefeed',
    u: 'd1a41f1362ca3ef64bbaa2c4bf605cb8',
    p: '6cb167ba87e1a756420d916fc234803c',
    sourceLen: 283,
    a1: A1,
    loadTs: 807840488,
    windowCount: 193,
    vmStateCount: 0,
    nowMs: 1794646849269,
    randomU32: 1999212277,
  });
  const EXPECT = 'mns0201_fVF5qcAShh5NgdfomWTvNa1GGkhuUlZn9aTmUxzoGF0myhkVAG6zfJCccbULLK/y0N7BYQBc7GJwK9dy9IZ5TLnTkb7BMoFPBxAqeb37bPP5zlMqyGMImDhwia4zuTOZZSwnw754GYjukZba8Dlb0IAtRHGjhBOU36vY5BxErtQQZ/ZcDnGALQkKR1v9/g53';
  console.log('regression sig len =', r.xs.length);
  console.log('REGRESSION MATCH =', r.xs === EXPECT);
  if (r.xs !== EXPECT) {
    console.log('got     =', r.xs);
    console.log('expected=', EXPECT);
  }
}
