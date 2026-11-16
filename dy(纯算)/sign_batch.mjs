// Batch sign: reads {"ua": "...", "items": [{"query": "...", "now": 123}, ...]} from stdin,
// prints a JSON array of a_bogus signatures in the same order.
import { sign } from './abogus_pure.mjs';

const chunks = [];
process.stdin.on('data', (chunk) => chunks.push(chunk));
process.stdin.on('end', () => {
  const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const { ua, items } = payload;
  const screen = payload.screen || '1699|309|1707|1019|1707|1019|1707|1067|Win32';
  const out = items.map(({ query, now }) => sign({
    query,
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
  }));
  process.stdout.write(JSON.stringify(out));
});
