import { loadPyodide } from "./runtime/pyodide/pyodide.mjs";

const RUNTIME_CACHE = "nihaixia-tcm-runtime-v1";
const BUILD_TAG = "__BUILD_ID__";

let dispatchRequest = null;

async function fetchCachedArrayBuffer(url) {
  const versionedUrl = `${url}?v=${BUILD_TAG}`;
  if (typeof caches !== "undefined") {
    try {
      const cache = await caches.open(RUNTIME_CACHE);
      const hit = await cache.match(versionedUrl);
      if (hit) {
        return await hit.arrayBuffer();
      }
      const resp = await fetch(versionedUrl, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${versionedUrl}`);
      const clone = resp.clone();
      await cache.put(versionedUrl, clone).catch(() => {});
      cache
        .keys()
        .then((reqs) =>
          Promise.all(
            reqs
              .filter((r) => r.url.includes("bundle.zip") && !r.url.includes(`v=${BUILD_TAG}`))
              .map((r) => cache.delete(r))
          )
        )
        .catch(() => {});
      return await resp.arrayBuffer();
    } catch (_err) {
      // Fallback straight to direct fetch
    }
  }
  const resp = await fetch(versionedUrl, { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${versionedUrl}`);
  return await resp.arrayBuffer();
}

async function initEngine() {
  self.postMessage({ type: "status", text: "正在启动浏览器 Python 运行时（Pyodide）…" });
  const pyodide = await loadPyodide({
    indexURL: "./runtime/pyodide/",
  });
  self.postMessage({ type: "status", text: "正在载入全库经典、汉唐经方与 17 册藏书索引包…" });
  const bundleBuf = await fetchCachedArrayBuffer("./runtime/bundle.zip");
  pyodide.unpackArchive(bundleBuf, "zip", { extractDir: "/tcm_brain" });
  pyodide.runPython(`
import sys
if "/tcm_brain" not in sys.path:
    sys.path.insert(0, "/tcm_brain")
from app.static_dispatch import dispatch_request as _tcm_dispatch_request
`);
  dispatchRequest = pyodide.globals.get("_tcm_dispatch_request");
  self.postMessage({ type: "ready" });
}

const initPromise = initEngine().catch((err) => {
  self.postMessage({ type: "init_error", error: String(err?.message || err) });
  throw err;
});

self.addEventListener("message", async (event) => {
  const msg = event.data || {};
  if (msg.type !== "api") return;
  try {
    await initPromise;
    const raw = dispatchRequest(
      String(msg.url || "/api/health"),
      String(msg.method || "GET"),
      String(msg.body || "")
    );
    self.postMessage({ type: "response", id: msg.id, raw: String(raw) });
  } catch (err) {
    self.postMessage({
      type: "response",
      id: msg.id,
      raw: JSON.stringify({ status: 500, body: { detail: String(err?.message || err) } }),
    });
  }
});
