import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
const NV8_ROOT = process.env.NV8_ROOT || "D:/develop_software/Nv8/src";
const { EdgeSandbox } = await import(new URL("public/edge-sandbox.js", "file:///" + NV8_ROOT.replace(/\\/g, "/") + "/"));

const root = new URL("./", import.meta.url);
const scriptPath = new URL("challenge.js", root);
const script = await readFile(scriptPath, "utf8");
const scriptSha256 = createHash("sha256").update(script).digest("hex");
const challengeUrl = "https://www.adidas.com.hk/CAcWH/8AFW/UuUB/1t86/p0G/kkY7p4Ecik/YhYNBgEB/ISxaV/DUMT1AY?v=5f584821-4bd1-4fec-0505-f1912fea17cd";
const html = `<!doctype html><html><head><script src="${challengeUrl}"></script></head><body></body></html>`;

const sandbox = await EdgeSandbox.create({
  page: { url: "https://www.adidas.com.hk/", html },
  limits: { timeoutMs: 120000 },
  replay: [{
    method: "GET",
    url: challengeUrl,
    status: 200,
    headers: { "content-type": "application/javascript" },
    body: script,
    type: "basic",
  }],
  networkRelay: {
    enabled: true,
    command: [process.env.PYTHON || "python", fileURLToPath(new URL("./relay_helper.py", import.meta.url))],
    origins: ["https://www.adidas.com.hk"],
    timeoutMs: 30000,
  },
});

try {
  await sandbox.evaluate(`new Promise(resolve => setTimeout(resolve, 8000))`);
  const requests = await sandbox.networkRequests();
  const summaries = requests
    .filter((request) => String(request.url ?? request.request?.url ?? "").includes("adidas.com.hk"))
    .map((request) => {
    const bodyValue = request.request?.body ?? request.body ?? request.bodyText ?? "";
    const body = typeof bodyValue === "string"
      ? bodyValue
      : bodyValue instanceof Uint8Array ? Buffer.from(bodyValue).toString("utf8") : "";
    const headerValue = request.request?.headers ?? request.headers;
    const headers = Array.isArray(headerValue)
      ? headerValue.map((item) => String(Array.isArray(item) ? item[0] : item).toLowerCase()).sort()
      : headerValue && typeof headerValue === "object"
        ? Object.keys(headerValue).map((name) => name.toLowerCase()).sort()
        : [];
    const responseHeaders = request.response?.headers ?? request.responseHeaders ?? {};
    const responseHeaderPairs = Array.isArray(responseHeaders)
      ? responseHeaders
      : Object.entries(responseHeaders);
    const responseHeaderMap = Object.fromEntries(responseHeaderPairs.map(([name, value]) => [String(name).toLowerCase(), value]));
    const responseBody = request.response?.body ?? request.responseBody ?? "";
    const responseBytes = typeof responseBody === "string"
      ? Buffer.from(responseBody, "base64")
      : responseBody instanceof Uint8Array ? Buffer.from(responseBody) : Buffer.alloc(0);
    let bodyKeys = [];
    try {
      const parsed = JSON.parse(body);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) bodyKeys = Object.keys(parsed);
    } catch {}
    return {
      topKeys: Object.keys(request).sort(),
      requestKeys: request.request && typeof request.request === "object" ? Object.keys(request.request).sort() : [],
      responseKeys: request.response && typeof request.response === "object" ? Object.keys(request.response).sort() : [],
      api: request.api ?? null,
      method: request.method ?? request.request?.method ?? "GET",
      url: request.url ?? request.request?.url,
      outcome: request.outcome,
      status: request.response?.status ?? request.status ?? null,
      headers,
      bodyLength: Buffer.byteLength(body),
      bodySha256: body ? createHash("sha256").update(body).digest("hex") : null,
      bodyKeys,
      responseBodyLength: responseBytes.length,
      responseSetCookieNames: responseHeaderMap["set-cookie"]
        ? [String(responseHeaderMap["set-cookie"]).split("=", 1)[0]]
        : [],
    };
    });
  const state = await sandbox.evaluate(`JSON.stringify({cookieNames:(document.cookie||"").split(";").map(x=>x.trim().split("=")[0]).filter(Boolean), title:document.title, readyState:document.readyState, ua:navigator.userAgent})`);
  const result = {
    mode: "nv8-live-session-relay",
    target: "https://www.adidas.com.hk/",
    challengeScript: { bytes: Buffer.byteLength(script), sha256: scriptSha256 },
    evaluation: {
      ok: true,
      valueType: "external-script",
      error: null,
    },
    state: state.value ?? null,
    requestCount: summaries.length,
    requests: summaries,
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} finally {
  await sandbox.close();
}
