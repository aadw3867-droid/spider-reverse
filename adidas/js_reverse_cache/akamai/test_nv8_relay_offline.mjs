import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
const NV8_ROOT = process.env.NV8_ROOT || "D:/develop_software/Nv8/src";
const { EdgeSandbox } = await import(new URL("public/edge-sandbox.js", "file:///" + NV8_ROOT.replace(/\\/g, "/") + "/"));

const broker = createServer((socket) => {
  socket.on("error", () => {});
  let buffer = "";
  socket.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    const newline = buffer.indexOf("\n");
    if (newline < 0) return;
    const request = JSON.parse(buffer.slice(0, newline));
    const response = {
      id: request.id,
      status: 200,
      statusText: "OK",
      headers: [["content-type", "text/plain"]],
      body: Buffer.from("relay-ok").toString("base64"),
      url: request.url,
    };
    socket.write(`${JSON.stringify(response)}\n`);
  });
});
await new Promise((resolve) => broker.listen(0, "127.0.0.1", resolve));
const port = broker.address().port;
process.env.ADIDAS_BROKER_PORT = String(port);
const helper = fileURLToPath(new URL("./relay_helper.py", import.meta.url));
const python = "C:\\Users\\31505\\AppData\\Local\\Programs\\Python\\Python311\\python.exe";
const sandbox = await EdgeSandbox.create({
  page: { url: "https://www.adidas.com.hk/", html: "<!doctype html><html><body></body></html>" },
  limits: { timeoutMs: 15000 },
  networkCapture: { enabled: true, maxEntries: 10 },
  networkRelay: {
    enabled: true,
    command: [python, helper, String(port)],
    origins: ["https://www.adidas.com.hk"],
    timeoutMs: 5000,
  },
});
try {
  let value = null;
  let evaluationError = null;
  try {
    const result = await sandbox.evaluate(`fetch("https://www.adidas.com.hk/offline-test", {method:"POST", body:"probe"}).then(r => r.text())`);
    value = result.value;
  } catch (error) {
    evaluationError = `${error}`;
  }
  const records = await sandbox.networkRequests();
  process.stdout.write(JSON.stringify({ result: value, evaluationError, records }, null, 2) + "\n");
  if (value !== "relay-ok") process.exitCode = 2;
} finally {
  await sandbox.close();
  broker.close();
}
