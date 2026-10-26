import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
const NV8_ROOT = process.env.NV8_ROOT || "D:/develop_software/Nv8/src";
const { EdgeSandbox } = await import(new URL("public/edge-sandbox.js", "file:///" + NV8_ROOT.replace(/\\/g, "/") + "/"));

const scriptUrl = process.env.ADIDAS_CHALLENGE_URL;
const scriptPath = process.env.ADIDAS_CHALLENGE_PATH;
if (!scriptUrl || !scriptPath) throw new Error("challenge URL and path are required");
const script = await readFile(scriptPath, "utf8");
const html = `<!doctype html><html><head><script src="${scriptUrl}"></script></head><body></body></html>`;
const relayPath = fileURLToPath(new URL("./relay_helper.py", import.meta.url));
const sandbox = await EdgeSandbox.create({
  page: { url: "https://www.adidas.com.hk/", html },
  limits: { timeoutMs: 60000 },
  replay: [{
    method: "GET",
    url: scriptUrl,
    status: 200,
    headers: { "content-type": "application/javascript" },
    body: script,
    type: "basic",
  }],
  networkCapture: { enabled: true, maxEntries: 20 },
  networkRelay: {
    enabled: true,
    command: [process.env.PYTHON || "python", relayPath, process.env.ADIDAS_BROKER_PORT],
    origins: ["https://www.adidas.com.hk"],
    timeoutMs: 30000,
  },
});

try {
  await sandbox.evaluate(`new Promise(resolve => setTimeout(resolve, 12000))`);
  const requests = await sandbox.networkRequests();
  const summary = requests.map((request) => {
    const bodyValue = request.request?.body ?? request.body ?? request.bodyText ?? "";
    const body = typeof bodyValue === "string"
      ? bodyValue
      : bodyValue instanceof Uint8Array ? Buffer.from(bodyValue).toString("utf8") : "";
    const parsed = (() => { try { return JSON.parse(body); } catch { return null; } })();
    const sensorBody = parsed && typeof parsed.body === "string" ? parsed.body : body;
    const headers = request.request?.headers ?? request.headers ?? [];
    const cookieHeader = Array.isArray(headers)
      ? headers.find((entry) => Array.isArray(entry) && String(entry[0]).toLowerCase() === "cookie")?.[1]
      : null;
    const cookieMeta = String(cookieHeader ?? "").split(";").map((part) => part.trim()).filter(Boolean).map((part) => {
      const index = part.indexOf("=");
      const name = index < 0 ? part : part.slice(0, index);
      const value = index < 0 ? "" : part.slice(index + 1);
      return { name, length: value.length };
    });
    return {
      method: request.method ?? request.request?.method ?? "GET",
      url: request.url ?? request.request?.url,
      status: request.response?.status ?? request.status ?? null,
      body_length: Buffer.byteLength(sensorBody),
      body_sha256: sensorBody ? createHash("sha256").update(sensorBody).digest("hex") : null,
      cookie_meta: cookieMeta,
      outcome: request.outcome ?? null,
    };
  });
  process.stdout.write(`${JSON.stringify({ request_count: summary.length, requests: summary }, null, 2)}\n`);
} finally {
  await sandbox.close();
}
