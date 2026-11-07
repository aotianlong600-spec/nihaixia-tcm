# Standalone Android runtime contract

This is the interface between independent workers. Clinical algorithms remain in shared Python.

## Python entry point

Module `app.mobile_api` exposes:

- `initialize(data_dir: str, knowledge_dir: str) -> str`: install/verify pack and initialize local storage, returns JSON `{status:200,body:{ready:true,...}}`, or a safe error envelope.
- `dispatch(method: str, path: str, body_json: str) -> str`: path is `/session`, `/consultations`, `/model/...` etc (no `/api` prefix). Returns JSON `{status:int,body:object|null}`. The wrapper may also use `{content_type:string,base64:string}` for a bounded binary response.

Only the fixed app page calls the JS bridge. There is no local listening TCP server or PC address.

## JavaScript to Java

`window.NihaixiaLocal.request(id,method,path,body)` schedules a local request. Java completes it with:

`window.dispatchEvent(new CustomEvent('nihaixia-local-response',{detail:{id,status,body,content_type?,base64?}}))`.

`session` body: `{authenticated:true,csrf_token:'local',access_configured:false,platform:'android',standalone:true}`. `ApiClient` records runtime flags; native local requests do not need LAN login/cookies. Never return API keys/OAuth credentials through this bridge.

## Java services called internally by Python

Class `com.nihaixia.local.NativeServices` (not exposed through JavascriptInterface):

- `configure(String dataDir)` sets the only allowed private runtime root.
- `http(String method,String url,String headersJson,String body,String requestId,int timeoutMs) -> String`: returns JSON `{status:int,headers:object,body:string}`; uses system HTTPS trust, no credentialed redirects, bounded response. No raw request/response logs.
- `cancelHttp(String requestId)` disconnects a pending request.
- `readSecret(String path) -> String|null` and `writeSecret(String path,String value)`: Android Keystore AES-GCM, encrypted bytes only on disk, atomic writes, paths inside runtime root, never exported to JS.

Python `app.mobile_models.MobileModels(data_dir:Path,http:callable,secrets:object)` handles model routes with `handle(method,path,body)->(status,body)`; `http` uses the signature above and secrets has `read(path)`/`write(path,value)`.

## Assets and originals

- Vue `frontend/dist` is bundled at asset root, served from `https://appassets.androidplatform.net/` via WebViewAssetLoader.
- The pure pack is bundled under `knowledge/`; bootstrap copies it to app-private files, then calls Python initialize with a separate runtime data directory.
- Python source is bundled with Chaquopy and `app` resources extracted for normal Path-based reads.
- PDF unit images use `https://appassets.androidplatform.net/local/pdf/<sha256>/<physical_page>.png`; Java PdfRenderer reads `data_dir/originals/<sha256>.pdf`. Physical pages remain canonical; printed labels are metadata.
- Original-file links use `/local/original/<sha256>` and are opened using a FileProvider restricted to the originals directory, never arbitrary paths or credential files.

## Navigation and storage

- Only bundled app origin retains the native bridge. External HTTPS links open the system browser; no trust-all TLS, no PC CA pin.
- SQLite and original files remain in app-private storage. Knowledge updates do not replace personal tables.
- Model profiles retain the existing public DTO and revision checks. Native cloud jobs validate completed output with the portable schema and shared `consultation_core.validate_result`.
