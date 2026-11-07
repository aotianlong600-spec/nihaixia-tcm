package com.nihaixia.local;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Message;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.ClientCertRequest;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.HttpAuthHandler;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;
import androidx.webkit.WebViewAssetLoader;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Standalone offline container. The Vue bundle and knowledge pack are bundled in the APK;
 * all clinical work runs in Chaquopy Python behind the narrow {@link LocalBridge}.
 *
 * <p>Only {@code https://appassets.androidplatform.net} may navigate inside this WebView.
 * External HTTPS links open the system browser. JavaScript, file, content, data, blob and
 * intent navigations are blocked. There is no PC address, LAN CA pin, trust-all handler or
 * WebView file access.</p>
 */
public class MainActivity extends Activity implements LocalBridge.Dispatcher {

    private static final String BRIDGE_NAME = "NihaixiaLocal";

    private WebView webView;
    private View bootstrapContainer;
    private ProgressBar bootstrapProgress;
    private TextView bootstrapStatus;
    private Button bootstrapRetry;

    private final ExecutorService worker = Executors.newCachedThreadPool();
    private final ExecutorService bootstrapExecutor = Executors.newSingleThreadExecutor();
    private WebViewAssetLoader assetLoader;
    private volatile boolean ready;
    private volatile boolean bootstrapping;
    private File runtimeRoot;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.web_view);
        bootstrapContainer = findViewById(R.id.bootstrap_container);
        bootstrapProgress = findViewById(R.id.bootstrap_progress);
        bootstrapStatus = findViewById(R.id.bootstrap_status);
        bootstrapRetry = findViewById(R.id.bootstrap_retry);
        bootstrapRetry.setOnClickListener(view -> startBootstrap());

        configureWebView();
        startBootstrap();
    }

    @SuppressLint({"SetJavaScriptEnabled", "JavascriptInterface"})
    private void configureWebView() {
        WebView.setWebContentsDebuggingEnabled(false);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false);
        settings.setDatabaseEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setLoadsImagesAutomatically(true);
        settings.setBlockNetworkLoads(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setGeolocationEnabled(false);
        settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setSaveFormData(false);

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(false);
        cookieManager.setAcceptThirdPartyCookies(webView, false);

        assetLoader = new WebViewAssetLoader.Builder()
                .setDomain(UrlPolicy.APP_HOST)
                .addPathHandler(UrlPolicy.PDF_PREFIX, path -> pdfResponse(UrlPolicy.PDF_PREFIX + path))
                .addPathHandler(UrlPolicy.ORIGINAL_PREFIX, path -> notFoundResponse())
                .addPathHandler("/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView.addJavascriptInterface(new LocalBridge(this), BRIDGE_NAME);
        webView.setWebViewClient(new LocalWebViewClient());
        webView.setWebChromeClient(new LocalWebChromeClient());
        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                    String mimeType, long contentLength) {
                Toast.makeText(MainActivity.this, R.string.blocked_link_message,
                        Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void startBootstrap() {
        if (bootstrapping) {
            return;
        }
        bootstrapping = true;
        ready = false;
        bootstrapProgress.setVisibility(View.VISIBLE);
        bootstrapStatus.setText(R.string.bootstrap_starting);
        bootstrapRetry.setVisibility(View.GONE);
        bootstrapContainer.setVisibility(View.VISIBLE);
        webView.setVisibility(View.GONE);

        bootstrapExecutor.execute(() -> {
            try {
                PythonBootstrap.initialize(MainActivity.this);
                runtimeRoot = PythonBootstrap.dataDir(MainActivity.this);
                ready = true;
                runOnUiThread(() -> {
                    bootstrapping = false;
                    if (isFinishing() || isDestroyed()) {
                        return;
                    }
                    bootstrapContainer.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                    webView.loadUrl(UrlPolicy.INDEX_URL);
                });
            } catch (Throwable failure) {
                ready = false;
                runOnUiThread(() -> {
                    bootstrapping = false;
                    if (isFinishing() || isDestroyed()) {
                        return;
                    }
                    bootstrapProgress.setVisibility(View.GONE);
                    bootstrapStatus.setText(R.string.bootstrap_failed_message);
                    bootstrapRetry.setVisibility(View.VISIBLE);
                    bootstrapContainer.setVisibility(View.VISIBLE);
                    webView.setVisibility(View.GONE);
                });
            }
        });
    }

    private void loadIndex() {
        if (ready) {
            webView.loadUrl(UrlPolicy.INDEX_URL);
        } else {
            startBootstrap();
        }
    }

    // ---- LocalBridge.Dispatcher -------------------------------------------------------

    @Override
    public void dispatch(String id, String method, String path, String body) {
        if (!BridgePolicy.validId(id)) {
            return;
        }
        if (!ready) {
            deliverError(id, 503, "本地运行时尚未就绪");
            return;
        }
        final String verb;
        final String target;
        final String payload;
        try {
            verb = BridgePolicy.normalizeMethod(method);
            target = BridgePolicy.normalizePath(path);
            payload = BridgePolicy.normalizeBody(body);
        } catch (IllegalArgumentException exception) {
            deliverError(id, 400, "本地请求无效");
            return;
        }
        worker.execute(() -> {
            try {
                String raw = PythonBootstrap.requireMobileApi()
                        .callAttr("dispatch", verb, target, payload).toString();
                deliverEnvelope(id, raw);
            } catch (Throwable failure) {
                deliverError(id, 500, "本地请求失败");
            }
        });
    }

    private void deliverEnvelope(String id, String raw) {
        int status;
        Object body;
        String contentType = "";
        String base64 = "";
        try {
            JSONObject envelope = new JSONObject(raw);
            status = envelope.optInt("status", 500);
            if (!envelope.has("body")) {
                body = JSONObject.NULL;
            } else {
                body = envelope.get("body");
            }
            contentType = envelope.optString("content_type", "");
            base64 = envelope.optString("base64", "");
        } catch (JSONException exception) {
            deliverError(id, 500, "本地响应无效");
            return;
        }
        if (status < 100 || status > 599) {
            status = 500;
        }
        try {
            JSONObject detail = new JSONObject();
            detail.put("id", id);
            detail.put("status", status);
            detail.put("body", body == null ? JSONObject.NULL : body);
            if (!contentType.isEmpty()) {
                detail.put("content_type", contentType);
            }
            if (!base64.isEmpty()) {
                detail.put("base64", base64);
            }
            dispatchEvent(detail);
        } catch (JSONException exception) {
            deliverError(id, 500, "本地响应无效");
        }
    }

    private void deliverError(String id, int status, String message) {
        try {
            JSONObject body = new JSONObject();
            body.put("detail", message);
            JSONObject detail = new JSONObject();
            detail.put("id", id);
            detail.put("status", status);
            detail.put("body", body);
            dispatchEvent(detail);
        } catch (JSONException ignored) {
            // Only fixed ASCII keys are used here.
        }
    }

    private void dispatchEvent(JSONObject detail) {
        final String script = "window.dispatchEvent(new CustomEvent('nihaixia-local-response',"
                + "{detail:" + detail.toString() + "}));";
        runOnUiThread(() -> {
            WebView view = webView;
            if (view == null) {
                return;
            }
            String current = view.getUrl();
            if (current == null || !UrlPolicy.isAppAssetUrl(current)) {
                return;
            }
            view.evaluateJavascript(script, null);
        });
    }

    // ---- WebView routing --------------------------------------------------------------

    private boolean handleNavigation(Uri uri, boolean mainFrame) {
        if (uri == null) {
            return true;
        }
        String url = uri.toString();
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();

        if (UrlPolicy.isAppAssetUrl(url)) {
            String sha = UrlPolicy.originalSha(uri.getPath());
            if (sha != null) {
                if (mainFrame) {
                    openOriginal(sha);
                }
                return true;
            }
            if (!UrlPolicy.isSafeAssetPath(uri.getPath())) {
                showBlocked();
                return true;
            }
            return false;
        }

        if ("https".equals(scheme) && UrlPolicy.isExternalHttps(url)) {
            if (mainFrame) {
                openExternalHttps(uri);
            }
            return true;
        }

        if (mainFrame) {
            showBlocked();
        }
        return true;
    }

    private void openExternalHttps(Uri uri) {
        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
        intent.addCategory(Intent.CATEGORY_BROWSABLE);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
            Toast.makeText(this, R.string.external_browser_opened, Toast.LENGTH_SHORT).show();
        } catch (ActivityNotFoundException exception) {
            new AlertDialog.Builder(this)
                    .setTitle(R.string.external_browser_title)
                    .setMessage(R.string.external_browser_missing)
                    .setPositiveButton(android.R.string.ok, null)
                    .show();
        }
        // No cookies, headers or session state are copied into the browser Intent.
    }

    private void openOriginal(String sha) {
        File root = runtimeRoot;
        if (root == null) {
            Toast.makeText(this, R.string.original_open_failed, Toast.LENGTH_SHORT).show();
            return;
        }
        try {
            File file = OriginalFiles.pdf(root, sha);
            if (!file.isFile()) {
                throw new IllegalStateException("original missing");
            }
            Uri uri = FileProvider.getUriForFile(
                    this, getPackageName() + ".fileprovider", file);
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, OriginalFiles.mimeType(file));
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        } catch (ActivityNotFoundException exception) {
            Toast.makeText(this, R.string.original_open_failed, Toast.LENGTH_SHORT).show();
        } catch (Exception exception) {
            Toast.makeText(this, R.string.original_open_failed, Toast.LENGTH_SHORT).show();
        }
    }

    private void showBlocked() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.blocked_link_title)
                .setMessage(R.string.blocked_link_message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private WebResourceResponse pdfResponse(String path) {
        File root = runtimeRoot;
        String sha = UrlPolicy.pdfSha(path);
        int page = UrlPolicy.pdfPage(path);
        if (root == null || sha == null || page < 1) {
            return notFoundResponse();
        }
        try {
            byte[] png = PdfPageRenderer.renderPng(root, sha, page);
            Map<String, String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-store");
            return new WebResourceResponse("image/png", "UTF-8", 200, "OK", headers,
                    new ByteArrayInputStream(png));
        } catch (Exception exception) {
            return notFoundResponse();
        }
    }

    private static WebResourceResponse notFoundResponse() {
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                Collections.<String, String>emptyMap(),
                new ByteArrayInputStream(new byte[0]));
    }

    private static WebResourceResponse blockedResponse() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked",
                Collections.<String, String>emptyMap(),
                new ByteArrayInputStream(new byte[0]));
    }

    @Override
    public void onBackPressed() {
        if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.main_menu, menu);
        return true;
    }

    @Override
    public boolean onPrepareOptionsMenu(Menu menu) {
        MenuItem reload = menu.findItem(R.id.action_reload);
        if (reload != null) {
            reload.setVisible(ready && webView.getVisibility() == View.VISIBLE);
        }
        return super.onPrepareOptionsMenu(menu);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == R.id.action_reload) {
            loadIndex();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        // The WebView has saveEnabled=false: history, forms and medical content are not
        // persisted across process death.
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        worker.shutdownNow();
        bootstrapExecutor.shutdownNow();
        if (webView != null) {
            webView.stopLoading();
            webView.clearHistory();
            webView.clearCache(true);
            webView.destroy();
            webView = null;
        }
        CookieManager.getInstance().removeAllCookies(null);
        CookieManager.getInstance().flush();
        super.onDestroy();
    }

    private final class LocalWebViewClient extends WebViewClient {

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (request == null) {
                return true;
            }
            return handleNavigation(request.getUrl(), request.isForMainFrame());
        }

        @SuppressWarnings("deprecation")
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return handleNavigation(url == null ? null : Uri.parse(url), true);
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view,
                WebResourceRequest request) {
            if (request == null || request.getUrl() == null) {
                return blockedResponse();
            }
            String url = request.getUrl().toString();
            if (UrlPolicy.isAppAssetUrl(url)) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }
            String scheme = request.getUrl().getScheme();
            if ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)
                    || "file".equalsIgnoreCase(scheme) || "content".equalsIgnoreCase(scheme)
                    || "ftp".equalsIgnoreCase(scheme)) {
                return blockedResponse();
            }
            return null;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request,
                WebResourceError error) {
            if (request != null && request.isForMainFrame() && ready) {
                showPageFailure();
            }
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            // Never call handler.proceed(); certificate errors stop the connection.
            handler.cancel();
        }

        @Override
        public void onReceivedClientCertRequest(WebView view, ClientCertRequest request) {
            request.cancel();
        }

        @Override
        public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler,
                String host, String realm) {
            handler.cancel();
        }
    }

    private void showPageFailure() {
        webView.setVisibility(View.GONE);
        bootstrapProgress.setVisibility(View.GONE);
        bootstrapStatus.setText(R.string.page_failed_message);
        bootstrapRetry.setVisibility(View.VISIBLE);
        bootstrapContainer.setVisibility(View.VISIBLE);
        ready = false;
    }

    private final class LocalWebChromeClient extends WebChromeClient {

        @Override
        public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture,
                Message resultMsg) {
            if (resultMsg == null || !(resultMsg.obj instanceof WebView.WebViewTransport)) {
                return false;
            }
            final WebView popup = new WebView(MainActivity.this);
            popup.setVisibility(View.GONE);
            WebSettings popupSettings = popup.getSettings();
            popupSettings.setJavaScriptEnabled(false);
            popupSettings.setAllowFileAccess(false);
            popupSettings.setAllowContentAccess(false);
            popupSettings.setBlockNetworkLoads(true);

            final boolean[] routed = {false};
            final Runnable destroyPopup = () -> {
                try {
                    popup.stopLoading();
                    popup.destroy();
                } catch (RuntimeException ignored) {
                    // Already torn down by WebView.
                }
            };
            popup.setWebViewClient(new WebViewClient() {
                private void route(WebView popupView, String url) {
                    if (url == null || url.isEmpty() || "about:blank".equals(url) || routed[0]) {
                        return;
                    }
                    routed[0] = true;
                    if (UrlPolicy.isAppAssetUrl(url)) {
                        webView.loadUrl(url);
                    } else if (UrlPolicy.isExternalHttps(url)) {
                        openExternalHttps(Uri.parse(url));
                    } else {
                        showBlocked();
                    }
                    popupView.postDelayed(destroyPopup, 500);
                }

                @Override
                public boolean shouldOverrideUrlLoading(WebView popupView,
                        WebResourceRequest request) {
                    route(popupView, request == null || request.getUrl() == null
                            ? null : request.getUrl().toString());
                    return true;
                }

                @SuppressWarnings("deprecation")
                @Override
                public boolean shouldOverrideUrlLoading(WebView popupView, String url) {
                    route(popupView, url);
                    return true;
                }

                @Override
                public void onPageStarted(WebView popupView, String url, Bitmap favicon) {
                    route(popupView, url);
                }

                @Override
                public void onReceivedSslError(WebView popupView, SslErrorHandler handler,
                        SslError error) {
                    handler.cancel();
                }
            });

            WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
            transport.setWebView(popup);
            resultMsg.sendToTarget();
            popup.postDelayed(destroyPopup, 10000);
            return true;
        }
    }
}
