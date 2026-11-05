# Explicit Pi inference bridge

Requires Node >=22.19.0. Install with `npm ci --ignore-scripts`, verify with
`npm run build` and `npm test`. The only direct runtime dependency is
`@earendil-works/pi-ai` pinned to 1.3.0; its transitive dependencies are locked.

Launch `node bridge.mjs` from Python with piped stdin/stdout. Send one UTF-8 JSON
line containing `base_url`, `api_key`, `model`, `input`, optional `system`,
`max_output_tokens` (1–4096, default 2048), and `timeout_ms` (1–90000, default
90000). `base_url` is the API directory, e.g. `https://example.org/v1`; the bridge
appends `/chat/completions`. Only HTTPS or HTTP loopback is accepted. Redirects
are rejected. This adapter requires OpenAI-compatible Chat Completions SSE,
`finish_reason: "stop"`, and the final `[DONE]` marker.

Stdout is exclusively JSONL: `{type:"delta",text}`, followed by exactly one
`{type:"done",text,usage,stop_reason:"stop"}` or `{type:"error",code,message}`.
The process exits after flushing that terminal frame, even while stdin remains
open. Send a later `{"type":"cancel"}` line to cancel. Partial text is only a
preview; it is never successful if the terminal result is an error. Successful
usage contains Pi's token counters (`input`, `output`, `cacheRead`, `cacheWrite`,
`totalTokens`); `{}` means the provider did not report usage. Costs are omitted
because custom model prices are unknown. Errors expose no provider body, key,
input, or stack. Exit code is 0 for success and 1 for error.

Each input line is limited to 1MiB; total stdout is limited to 128KiB including
JSON framing and repeated final text. Raw SSE is capped at 2MiB. The parent must
read stdout promptly and still enforce its own subprocess deadline and validate
the final clinical explanation. Cancellation cannot guarantee remote billing has
stopped. No environment/file credential fallback, retries, tool execution,
or coding-agent packages are enabled.
The dedicated child clears its inherited environment before dynamically loading
Pi, preventing the underlying SDK's organization/custom-header/logging defaults.
The launcher must also omit Node startup variables such as `NODE_OPTIONS` and
`NODE_DEBUG`, which can take effect before JavaScript begins.

Tests launch real Node subprocesses against a local synthetic HTTP SSE server;
they never contact a model service or use real credentials.

`auth_mode: "codex"` selects a separate, fixed OpenAI Codex Responses text
transport (`codex.mjs`), using an explicit access token in the private `api_key`
field. SSE must contain a completed response. No tools, websocket transport,
redirects or automatic credential lookup are enabled. `--models` returns the
SDK catalog, not account entitlements.

`oauth.mjs` is a separate PRIVATE Python-to-Node pipe for `login` (browser/device)
and `refresh`. Its terminal credential frame contains secrets and must never be
logged or exposed through HTTP. Python stores it with Windows DPAPI. The web UI
receives only validated authorization links, device codes and status. Login
cancellation does not replace an existing credential. A synthetic test passing
does not establish that a real account can authorize or run a selected model.
