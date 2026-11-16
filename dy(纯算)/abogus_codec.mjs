// a_bogus 容器编解码：base64(Z255) <-> 129B 载荷 <-> (4B 头 + 8B 头 + #148 展开体)
// 用法: node abogus_codec.mjs <a_bogus字符串或文件>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ALPHA = {
  std: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=',
  s1: 'Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=',
  s2: 'Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=',
  s3: 'ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe',
  s4: 'Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe',
};

export function b64enc(bytes, alphabet) {
  const n = alphabet.length >= 65 ? 64 : 64;
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i + 1], b2 = bytes[i + 2];
    out += alphabet[b0 >> 2];
    out += alphabet[((b0 & 3) << 4) | ((b1 ?? 0) >> 4)];
    out += b1 === undefined ? '=' : alphabet[((b1 & 15) << 2) | ((b2 ?? 0) >> 6)];
    out += b2 === undefined ? '=' : alphabet[b2 & 63];
  }
  return out;
}

export function b64dec(str, alphabet) {
  const idx = new Map();
  for (let i = 0; i < 64; i++) idx.set(alphabet[i], i);
  const out = [];
  let acc = 0, bits = 0;
  for (const ch of str) {
    if (ch === '=') break;
    const v = idx.get(ch);
    if (v === undefined) throw new Error('非法 base64 字符: ' + ch);
    acc = (acc << 6) | v;
    bits += 6;
    if (bits >= 8) { bits -= 8; out.push((acc >> bits) & 255); }
  }
  return Buffer.from(out);
}

// #148: 3 字节 -> 4 字节，数据位拆分 + 每字节 2 bit 随机位（随机位实测相互独立，不参与语义）
//   out0 = (rand & 145) | (in0 & 110)   ; 110|145 = 0xFF
//   out1 = (rand & 66)  | (in1 & 189)   ; 189|66  = 0xFF
//   out2 = (rand & 44)  | (in2 & 211)   ; 211|44  = 0xFF
//   out3 = (in0 & 145) | (in1 & 66) | (in2 & 44)
export const M = { a: 110, b: 145, c: 189, d: 66, e: 211, f: 44 };

export function expand148(data, rand = () => (Math.random() * 1000) & 255) {
  const out = [];
  let i = 0;
  while (i + 3 <= data.length) {
    const [x, y, z] = [data[i], data[i + 1], data[i + 2]];
    const r = rand() & 255;
    out.push(((x & M.a) | (r & M.b)) & 255);
    out.push(((y & M.c) | (r & M.d)) & 255);
    out.push(((z & M.e) | (r & M.f)) & 255);
    out.push(((x & M.b) | (y & M.d) | (z & M.f)) & 255);
    i += 3;
  }
  while (i < data.length) out.push(data[i++]);
  return Buffer.from(out);
}

export function collapse148(expanded) {
  const out = [];
  let i = 0;
  while (i + 4 <= expanded.length) {
    const [o0, o1, o2, o3] = [expanded[i], expanded[i + 1], expanded[i + 2], expanded[i + 3]];
    out.push(((o0 & M.a) | (o3 & M.b)) & 255);
    out.push(((o1 & M.c) | (o3 & M.d)) & 255);
    out.push(((o2 & M.e) | (o3 & M.f)) & 255);
    i += 4;
  }
  while (i < expanded.length) out.push(expanded[i++]);
  return Buffer.from(out);
}

// 129B 载荷 = 4B 头 + 8B 头 + 展开体
export function splitPayload(payload) {
  const p = Buffer.from(payload);
  const head4 = p.subarray(0, 4);
  const head8 = p.subarray(4, 12);
  const body = p.subarray(12);
  return { head4, head8, body, core: collapse148(body) };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const arg = process.argv[2];
  if (!arg) { console.error('用法: node abogus_codec.mjs <a_bogus>'); process.exit(1); }
  const sig = fs.existsSync(arg) ? fs.readFileSync(arg, 'utf8').trim() : arg;
  const payload = b64dec(sig, ALPHA.s4);
  console.log('a_bogus len =', sig.length, ' payload =', payload.length, 'B');
  console.log('payload hex =', payload.toString('hex'));
  const { head4, head8, body, core } = splitPayload(payload);
  console.log('head4 =', [...head4].join(','), ' head8 =', [...head8].join(','));
  console.log('expanded body =', body.length, 'B -> core =', core.length, 'B');
  console.log('core hex =', core.toString('hex'));
  console.log('core ascii tail =', JSON.stringify(core.subarray(48).toString('latin1')));
  const re = b64enc(expand148(core, () => 0), ALPHA.s4);
  console.log('round-trip(rand=0,仅校验数据位): 前12B一致 =',
    re.slice(0, 16) === sig.slice(0, 16));
}
