/**
 * sign.js — 抖音主页 aweme/post 双签名生成器（Node 侧，传统补环境）
 *
 * 流程（与真实浏览器链路一致）：
 *   Stage A (BDMS) : 先装假的 fetch -> 执行 bdms -> bdms.init() -> fetch(stage1Url)
 *                     -> 捕获的 URL 被追加了 a_bogus
 *   Stage B (secsdk): 执行 secsdk -> 设置 SSR_RENDER_DATA / _secsdk_uifid
 *                     -> window.use('webSignUrl')(stage1Url + verifyFp/fp)
 *                     -> 返回追加了 uifid + timestamp + x-secsdk-web-signature 的 URL
 *
 * 输入：stdin 的 JSON 配置
 * 输出：一行标记 + 一行 JSON artifact
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { createEnv } = require('./env.js');

const MARKER = '===== DOUYIN SIGN ARTIFACT =====';
const ROOT = __dirname;

// bdms 内部一些无关紧要的遥测路径会调用不存在的函数并产生 unhandledRejection，
// 与最终 a_bogus / secsig 无关，这里静默掉，避免输出噪声。
process.on('unhandledRejection', () => {});

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on('data', (c) => chunks.push(c));
    process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    process.stdin.on('error', reject);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const cfg = JSON.parse(await readStdin());

  // 1. 构建浏览器沙箱（传统补环境）
  const env = createEnv({
    ua: cfg.ua,
    pageUrl: cfg.pageUrl,
    screen: cfg.screen,
    cookies: cfg.cookies,
    localStorage: cfg.localStorage,
  });
  const sandbox = env.sandbox;
  sandbox.queueMicrotask = (f) => Promise.resolve().then(f);
  vm.createContext(sandbox);

  function run(src, filename) {
    return vm.runInContext(src, sandbox, { filename: filename || 'sdk.js', timeout: 120000 });
  }

  const notes = [];

  // 2. Stage A: BDMS -> a_bogus
  run('window.__capturedSigned = ""; window.fetch = function(input){ try { window.__capturedSigned = typeof input === "string" ? input : (input && input.url) || String(input); } catch(e){} return Promise.resolve({ok:true,status:204,text:function(){return Promise.resolve("");},json:function(){return Promise.resolve({});}}); }; void 0;', 'fake-fetch.js');

  const bdmsSource = fs.readFileSync(path.join(ROOT, 'bdms_1.0.1.19_fix.js'), 'utf8');
  try {
    run(bdmsSource, 'bdms_1.0.1.19_fix.js');
  } catch (e) {
    notes.push('bdms load failed: ' + e.message);
  }

  try {
    run('if (window.bdms && typeof window.bdms.init === "function") { window.bdms.init({ aid: 6383, paths: ["/aweme/v1/web/aweme/post/"], pageId: 1 }); } else { throw new Error("no window.bdms.init"); } void 0;', 'bdms-init.js');
  } catch (e) {
    notes.push('bdms init failed: ' + e.message);
  }

  try {
    run('window.fetch(' + JSON.stringify(cfg.stage1Url) + ').catch(function(){}); void 0;', 'trigger-fetch.js');
  } catch (e) {}
  await sleep(600);

  const signedStageA = run('String(window.__capturedSigned || "")', 'read-captured.js');
  const stageAHasBogus = signedStageA.includes('a_bogus=');

  // 3. Stage B: secsdk -> webSignUrl -> x-secsdk-web-signature
  const secsdkSource = fs.readFileSync(path.join(ROOT, 'secsdk_runtime_bundler_34.js'), 'utf8');
  try {
    run(secsdkSource, 'secsdk_runtime_bundler_34.js');
  } catch (e) {
    notes.push('secsdk load failed: ' + e.message);
  }

  run('window.SSR_RENDER_DATA = ' + JSON.stringify(cfg.ssr || { app: { odin: { user_id: '0', user_unique_id: '0' } } }) + '; window._secsdk_uifid = ' + JSON.stringify(cfg.uifid || '') + '; void 0;', 'set-state.js');
  await sleep(400);

  const result = { ok: false, notes };
  try {
    const stage2Input = signedStageA + (cfg.appendQuery ? '&' + String(cfg.appendQuery).replace(/^&/, '') : '');
    const expr = '(function(){ var f = window.use("webSignUrl"); if (typeof f !== "function") return JSON.stringify({ err: "webSignUrl not function: " + typeof f }); try { var out = f(' + JSON.stringify(stage2Input) + '); return JSON.stringify({ url: out && out.url, headers: out && out.headers ? Object.keys(out.headers) : null }); } catch (e) { return JSON.stringify({ err: String(e && e.message) }); } })()';
    const raw = run(expr, 'webSignUrl-call.js');
    const stageBOut = JSON.parse(raw || '{}');
    if (stageBOut.url) {
      result.ok = true;
      result.url = String(stageBOut.url);
      result.hasBogus = result.url.includes('a_bogus=');
      result.hasSecsig = result.url.includes('x-secsdk-web-signature=');
      result.stageAHasBogus = stageAHasBogus;
    } else {
      notes.push('webSignUrl returned no url: ' + JSON.stringify(stageBOut).slice(0, 300));
    }
  } catch (e) {
    notes.push('stage B failed: ' + ((e && e.stack) || String(e)));
  }

  console.log(MARKER);
  console.log(JSON.stringify(result));
  process.exit(0);
}

main().catch((e) => {
  console.error('[sign] fatal: ' + ((e && e.stack) || e));
  process.exit(1);
});
