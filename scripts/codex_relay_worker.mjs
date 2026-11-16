/**
 * Optional Cloudflare Worker / Deno CORS Relay for pure-static GitHub Pages users
 * who want to use OpenAI Codex (ChatGPT OAuth) directly from https://*.github.io.
 *
 * Security: Strictly allow-lists only official OpenAI Auth and ChatGPT Codex hosts
 * so this relay cannot be abused as an open SSRF proxy.
 *
 * Deploy free on Cloudflare Workers (or `npx wrangler deploy`):
 *   Expected POST JSON body: { url, method, headers, body }
 */

const ALLOWED_ORIGINS = new Set([
  "https://aotianlong600-spec.github.io",
  "http://127.0.0.1:8767",
  "http://127.0.0.1:8768",
  "http://localhost:8767",
  "http://localhost:8768",
]);

function isAllowedTarget(rawUrl) {
  let u;
  try {
    u = new URL(String(rawUrl || ""));
  } catch {
    return false;
  }
  if (u.protocol !== "https:") return false;
  if (u.hostname === "auth.openai.com") {
    return (
      u.pathname === "/oauth/token" ||
      u.pathname.startsWith("/api/accounts/deviceauth/")
    );
  }
  if (u.hostname === "chatgpt.com") {
    return u.pathname.startsWith("/backend-api/codex/");
  }
  if (u.hostname === "opencode.ai" && u.pathname.startsWith("/zen/")) {
    return true;
  }
  return false;
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const allowOrigin = ALLOWED_ORIGINS.has(origin) ? origin : "*";
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

export default {
  async fetch(request) {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return new Response(JSON.stringify({ ok: true, service: "nihaixia-codex-cors-relay" }), {
        status: 200,
        headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
      });
    }
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
      });
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
        status: 400,
        headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
      });
    }

    const targetUrl = String(payload?.url || "");
    if (!isAllowedTarget(targetUrl)) {
      return new Response(JSON.stringify({ error: "Target URL is not in allow-list" }), {
        status: 403,
        headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
      });
    }

    const method = String(payload?.method || "POST").toUpperCase();
    const forwardHeaders = new Headers();
    const rawHeaders = payload?.headers && typeof payload.headers === "object" ? payload.headers : {};
    for (const [k, v] of Object.entries(rawHeaders)) {
      const lower = k.toLowerCase();
      if (["host", "origin", "referer", "content-length"].includes(lower)) continue;
      if (v != null) forwardHeaders.set(k, String(v));
    }

    const body =
      method === "GET" || method === "HEAD" || payload?.body == null
        ? undefined
        : typeof payload.body === "string"
        ? payload.body
        : JSON.stringify(payload.body);

    const upstream = await fetch(targetUrl, {
      method,
      headers: forwardHeaders,
      body,
    });

    const outHeaders = new Headers(cors);
    const contentType = upstream.headers.get("Content-Type");
    if (contentType) outHeaders.set("Content-Type", contentType);
    outHeaders.set("Cache-Control", "no-store");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: outHeaders,
    });
  },
};
