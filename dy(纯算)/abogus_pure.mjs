// a_bogus pure-JS signer (bdms 1.0.1.19-fix.01), reimplemented from #150/#146/#147/#148/#142/#280.
// Verified: reproduces vm/hit.json core 87B and final a_bogus byte-for-byte, plus all 8 vm/timeseries.json signatures.
// Usage: node tools/abogus_pure.mjs --selftest
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { b64enc, b64dec, expand148, collapse148, ALPHA } from './abogus_codec.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VM = path.join(HERE, '..', 'vm');

const S3 = ALPHA.s3, S4 = ALPHA.s4;
const sm3 = (buf) => crypto.createHash('sm3').update(buf).digest();
const bytes = (s) => Buffer.from(s, 'latin1');

// #280: RC4 variant. S starts reversed (255-i); KSA recurrence j = j*(S[i]+1)+key[i%len].
function rc4(keyStr, dataStr) {
  const S = new Uint8Array(256);
  for (let i = 0; i < 256; i++) S[i] = 255 - i;
  let j = 0;
  for (let i = 0; i < 256; i++) {
    j = (j * (S[i] + 1) + keyStr.charCodeAt(i % keyStr.length)) % 256;
    const t = S[i]; S[i] = S[j]; S[j] = t;
  }
  let out = '';
  let a = 0; j = 0;
  for (let k = 0; k < dataStr.length; k++) {
    a = (a + 1) % 256;
    j = (j + S[a]) % 256;
    const t = S[a]; S[a] = S[j]; S[j] = t;
    out += String.fromCharCode(S[(S[a] + S[j]) % 256] ^ dataStr.charCodeAt(k));
  }
  return out;
}

// #142 + #130("s3"): blob = b64(rc4([hi,lo,cap17], UA), s3), 148 chars.
export function makeBlob(ua, cap16 = 129, cap17 = 14) {
  const key = String.fromCharCode((cap16 >> 8) & 255, cap16 & 255, cap17 & 255);
  return b64enc(bytes(rc4(key, ua.trim())), S3);
}

// #146: arg=[b0,b1]; mode 0 = random/random, 1 = random/#143, 2 = #144/#145.
function pack146(b0, b1, cap7, cap8) {
  return [
    (cap7 & 170) | (b0 & 85),
    (cap7 & 85) | (b0 & 170),
    (cap8 & 170) | (b1 & 85),
    (cap8 & 85) | (b1 & 170),
  ];
}

// #143: browser-name branch not hit -> 0..39.
const rnd143 = (rnd) => (rnd() * 40) & 255;
// #144: browser["4"]&64 not hit -> 0..239.
const rnd144 = (rnd) => {
  const x = (rnd() * 240) & 255;
  return x > 109 ? x + (x % 2) + 1 : x;
};
// #145: base mask & 77, OR permission bits (observed 255).
const rnd145 = (rnd, perms = 255) => ((rnd() * 255) & 77) | (perms & ~77);

export function genHead4(rnd = Math.random) {
  const x = rnd() * 65535;
  return pack146(3, 82, x & 255, rnd143(rnd));
}
export function genHead8(rnd = Math.random, perms = 255) {
  const x = rnd() * 65535;
  return [
    ...pack146(1, 0, x & 255, (x >> 8) & 255),
    ...pack146(1, 0, rnd144(rnd), rnd145(rnd, perms)),
  ];
}

// Faithful to #150: only when buf[start] === val does it skip the run of identical values.
function scan(buf, start, val, flags, flagBit) {
  let v = buf[start];
  if (v === val) {
    let i = start;
    for (;;) {
      i++;
      if (i < buf.length) v = buf[i];
      else { v = val + 1; break; }
      if (v !== val) break;
    }
  }
  return (flags & flagBit) ? val : v;
}

const PREFIX_ORDER = [
  'cap34', 'cap44', 'cap56', 'cap61', 'cap73', 'cap29', 'cap70', 'cap45', 'cap35', 'cap49',
  'cap38', 'cap66', 'cap51', 'cap68', 'cap28', 'cap48', 'cap64', 'cap47', 'cap30', 'cap71',
  'cap26', 'cap55', 'cap31', 'cap69', 'cap59', 'cap40', 'cap62', 'cap63', 'cap27', 'cap72',
  'cap41', 'cap74', 'cap57', 'cap52', 'cap42', 'cap39', 'cap33', 'cap67', 'cap53', 'cap43',
  'cap65', 'cap46', 'cap36', 'cap24', 'cap60', 'cap32', 'cap79', 'cap80', 'cap84', 'cap85',
];

export function buildCore({
  now, ink, h2, h4, h5, head8,
  cap16 = 129, cap17 = 14, cap27 = 6, flags = 15, cap12 = 3,
  pageId = 1, aid = 6383, screen = '0|0|0|0|1920|1040|1920|1080|Win32', cap28 = 3,
}) {
  const cap29 = now & 255, cap30 = (now >> 8) & 255, cap31 = (now >> 16) & 255,
    cap32 = (now >> 24) & 255, cap33 = (now / 4294967296) & 255, cap34 = (now / 1099511627776) & 255;
  const cap60 = ink & 255, cap61 = (ink >> 8) & 255, cap62 = (ink >> 16) & 255,
    cap63 = (ink >> 24) & 255, cap64 = (ink / 4294967296) & 255, cap65 = (ink / 1099511627776) & 255;
  const cap35 = cap16 & 255, cap36 = (cap16 >> 8) & 255;
  const cap38 = flags & 255, cap39 = (flags >> 8) & 255;
  const cap44 = cap17 & 255, cap45 = (cap17 >> 8) & 255, cap46 = (cap17 >> 16) & 255, cap47 = (cap17 >> 24) & 255;
  const cap48 = h2[9], cap49 = h2[18], cap52 = h4[10], cap53 = h4[19], cap56 = h5[11], cap57 = h5[21];
  const cap51 = scan(h2, 3, 11, flags, 2);
  const cap55 = scan(h4, 4, 8, flags, 4);
  const cap59 = scan(h5, 5, 12, flags, 8);
  const cap26 = Math.floor((now - 1721836800000) / 1000 / 60 / 60 / 24 / 14) & 255;
  const cap66 = cap12;
  const cap67 = pageId & 255, cap68 = (pageId >> 8) & 255, cap69 = (pageId >> 16) & 255, cap70 = (pageId >> 24) & 255;
  const cap71 = aid & 255, cap72 = (aid >> 8) & 255, cap73 = (aid >> 16) & 255, cap74 = (aid >> 24) & 255;
  const cap24 = 41, cap40 = 0, cap41 = 0, cap42 = 0, cap43 = 0;
  const cap79 = screen.length & 255, cap80 = (screen.length >> 8) & 255;

  const cap81 = ((now + 3) & 255) + ',';
  const cap82 = [...cap81].map((c) => c.charCodeAt(0));
  const cap84 = cap82.length & 255, cap85 = (cap82.length >> 8) & 255;

  const caps = {
    cap24, cap26, cap27, cap28, cap29, cap30, cap31, cap32, cap33, cap34, cap35, cap36,
    cap38, cap39, cap40, cap41, cap42, cap43, cap44, cap45, cap46, cap47, cap48, cap49,
    cap51, cap52, cap53, cap55, cap56, cap57, cap59, cap60, cap61, cap62, cap63, cap64,
    cap65, cap66, cap67, cap68, cap69, cap70, cap71, cap72, cap73, cap74, cap79, cap80,
    cap84, cap85,
  };

  let ck = 0;
  for (const v of head8) ck ^= v;
  for (const v of Object.values(caps)) ck ^= v;

  return Buffer.concat([
    Buffer.from(PREFIX_ORDER.map((k) => caps[k])),
    bytes(screen),
    Buffer.from(cap82),
    Buffer.from([ck]),
  ]);
}

export function sign({
  query, body = '', ua, now = Date.now(), ink,
  cap16 = 129, cap17 = 14, cap27 = 6, flags = 15, cap12 = 3,
  pageId = 1, aid = 6383, screen = '0|0|0|0|1920|1040|1920|1080|Win32', cap28 = 3,
  head4, head8, rand = Math.random, perms = 255,
}) {
  if (!ua) throw new Error('ua required');
  if (ink === undefined) ink = now - 1;
  const h2 = sm3(sm3(bytes(query + 'dhzx')));
  const h4 = sm3(sm3(bytes(body + 'dhzx')));
  const h5 = sm3(bytes(makeBlob(ua, cap16, cap17)));
  const h4b = head4 || genHead4(rand);
  const h8 = head8 || genHead8(rand, perms);
  const core = buildCore({ now, ink, h2, h4, h5, head8: h8, cap16, cap17, cap27, flags, cap12, pageId, aid, screen, cap28 });
  const expanded = expand148(core, () => (rand() * 1000) & 255);
  const enc = rc4(String.fromCharCode(211), String.fromCharCode(...h8) + String.fromCharCode(...expanded));
  return b64enc(Buffer.concat([Buffer.from(h4b), bytes(enc)]), S4);
}

export function parse(sig) {
  const payload = b64dec(sig, S4);
  return {
    payloadLen: payload.length,
    head4: [...payload.subarray(0, 4)],
    head8: [...payload.subarray(4, 12)],
    core: [...collapse148(payload.subarray(12))],
  };
}

function selftest() {
  const capsRaw = JSON.parse(fs.readFileSync(path.join(VM, 'caps_at_hit.json'), 'utf8'));
  const hit = JSON.parse(fs.readFileSync(path.join(VM, 'hit.json'), 'utf8'));
  const hashlog = JSON.parse(fs.readFileSync(path.join(VM, 'hashlog.json'), 'utf8'));
  const p280 = JSON.parse(fs.readFileSync(path.join(VM, 'p280.json'), 'utf8'));
  const caps = {};
  for (const [k, v] of Object.entries(capsRaw)) {
    const t = v.slice(0, 2), b = v.slice(2);
    if (t === 'n:') caps[k] = Number(b);
    else if (t === 's:') caps[k] = String.fromCharCode(...b.split(',').map(Number));
    else caps[k] = b.split(',').map(Number);
  }
  const core = caps[88];
  const cap14 = core[5] + core[18] * 256 + core[22] * 65536 + core[45] * 16777216 + core[36] * 4294967296 + core[0] * 1099511627776;
  const ink = core[44] + core[3] * 256 + core[26] * 65536 + core[27] * 16777216 + core[16] * 4294967296 + core[40] * 1099511627776;
  const cap16 = core[8] | (core[42] << 8);
  const cap17 = core[1] | (core[7] << 8) | (core[41] << 16) | (core[17] << 24);
  const flags = core[10] | (core[35] << 8);
  const pageId = core[37] | (core[13] << 8) | (core[23] << 16) | (core[6] << 24);
  const aid = core[19] | (core[29] << 8) | (core[4] << 16) | (core[31] << 24);
  const head8 = caps[86], head4 = caps[89], exp = caps[90];
  const rands = [];
  for (let i = 0; i + 4 <= exp.length; i += 4) {
    rands.push(((exp[i] & 145) | (exp[i + 1] & 66) | (exp[i + 2] & 44)) & 255);
  }
  const query = hashlog.find((e) => e[0] === 'write' && e[1] === 617)[2].replace(/dhzx$/, '');
  const ua = String.fromCharCode(...p280[0].a[1]);
  const h2 = sm3(sm3(bytes(query + 'dhzx')));
  const h4 = sm3(sm3(bytes('dhzx')));
  const h5 = sm3(bytes(makeBlob(ua, cap16, cap17)));
  const core2 = buildCore({
    now: cap14, ink, h2, h4, h5, head8, cap16, cap17, flags,
    cap27: core[28], cap28: core[14], cap12: core[11], pageId, aid, screen: caps[76],
  });
  let idx = 0;
  const expanded = expand148(core2, () => rands[idx++]);
  const enc = rc4(String.fromCharCode(211), String.fromCharCode(...head8) + String.fromCharCode(...expanded));
  const sig = b64enc(Buffer.concat([bytes(head4), bytes(enc)]), S4);
  const okCore = core2.equals(Buffer.from(core));
  const okSig = sig === hit.value;
  console.log('env: cap16=%d cap17=%d flags=%d pageId=%d aid=%d cap27=%d cap28=%d cap12=%d',
    cap16, cap17, flags, pageId, aid, core[28], core[14], core[11]);
  console.log('core %dB match :', core2.length, okCore ? 'OK' : 'FAIL');
  console.log('a_bogus match  :', okSig ? 'OK' : 'FAIL');
  if (!okCore || !okSig) {
    console.log('built :', core2.toString('hex'));
    console.log('sample:', Buffer.from(core).toString('hex'));
    console.log('sig built :', sig);
    console.log('sig sample:', hit.value);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--selftest')) {
    selftest();
  } else {
    const q = process.argv[2] || '';
    const ua = process.argv[3] || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36';
    const sig = sign({ query: q, ua });
    console.log(sig);
    console.log(JSON.stringify(parse(sig), null, 2));
  }
}
