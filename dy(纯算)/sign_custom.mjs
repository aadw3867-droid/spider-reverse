// 按恢复的 Edge/157 环境签名：node tools/sign_custom.mjs <query> <ua> <now> <screen>
import { sign } from './abogus_pure.mjs';

const q = process.argv[2];
const ua = process.argv[3];
const now = Number(process.argv[4]);
const screen = process.argv[5] || '1699|309|1707|1019|1707|1019|1707|1067|Win32';

const sig = sign({
  query: q,
  ua,
  now,
  ink: now - 1,
  cap16: 1,
  cap17: 0,
  flags: 129,
  pageId: 6241,
  aid: 6383,
  cap27: 6,
  cap28: 3,
  cap12: 3,
  screen,
});
console.log(sig);
