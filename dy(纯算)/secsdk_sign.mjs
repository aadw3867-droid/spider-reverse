import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Decoded from the string table in runtime_bundler_34.js; tied to this SDK build.
const WEB_SIGN_KEY = 'A96D855A08C0A9707F8BEF0D9A527E4E';

export function signSecsdk({ uifid, timestamp, query }) {
  if (!uifid || !timestamp || typeof query !== 'string' || !query) {
    throw new Error('uifid, timestamp and the exact unsigned query are required');
  }
  if (query.includes('x-secsdk-web-signature=')) {
    throw new Error('query must not contain x-secsdk-web-signature');
  }
  return crypto.createHash('md5')
    .update(`${uifid}_${timestamp}_${WEB_SIGN_KEY}_${query}`, 'utf8')
    .digest('hex');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === '--selftest') {
    const sample = {
      uifid: 'demo-uifid',
      timestamp: '1794815438',
      query: 'aid=6383&uifid=demo-uifid&timestamp=1794815438',
    };
    const actual = signSecsdk(sample);
    if (actual !== '46bf185497d77d1e6160f91cbeaf3bb8') {
      throw new Error(`signature mismatch: ${actual}`);
    }
    console.log('x-secsdk-web-signature synthetic vector: OK');
  } else {
    const [uifid, timestamp, query] = process.argv.slice(2);
    console.log(signSecsdk({ uifid, timestamp, query }));
  }
}
