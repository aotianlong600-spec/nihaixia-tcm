package com.nihaixia.workbench;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Message;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.ClientCertRequest;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.HttpAuthHandler;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Native Android container for the existing Vue workbench served by the PC.
 *
 * <p>Security invariants: only validated private-LAN HTTPS roots are persisted; the custom
 * CA is the only trust anchor (network security config); TLS errors are never ignored;
 * external HTTPS links leave the app for the system browser without transferring cookies;
 * other schemes are rejected; there is no JavaScript bridge, file/content access,
 * cleartext traffic, mixed content, or WebView state/content persistence.</p>
 */
public class MainActivity extends Activity {

    private static final String PREFS_NAME = "connection";
    private static final String PREF_SERVER_ROOT = "server_root";
    private static final String DOWNLOAD_BLOCKED_SCHEME = "nihaixia-blocked-download";

    /**
     * Blob/data downloads are not reliably reported by DownloadListener. This page-side
     * guard only translates such clicks into a blocked custom-scheme navigation so the
     * user gets an explicit "use the PC" message. It is not a native JS bridge.
     */
    private static final String DOWNLOAD_GUARD_JS =
            "(function(){if(window.__nihaixiaDownloadGuard){return;}"
            + "window.__nihaixiaDownloadGuard=true;"
            + "document.addEventListener('click',function(e){var t=e.target;"
            + "if(!t||typeof t.closest!=='function'){return;}"
            + "var a=t.closest('a');if(!a){return;}"
            + "var h=a.getAttribute('href')||'';"
            + "if(a.hasAttribute('download')||h.indexOf('blob:')===0||h.indexOf('data:')===0){"
            + "e.preventDefault();e.stopPropagation();"
            + "window.location.href='nihaixia-blocked-download:';}},true);})();";

    private WebView webView;
    private ProgressBar progress;
    private View setupContainer;
    private View errorContainer;
    private TextView setupError;
    private TextView errorTitle;
    private TextView errorMessage;
    private EditText addressInput;

    private SharedPreferences preferences;
    private String normalizedRoot;
    private boolean tlsFailureShown;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        preferences = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        webView = findViewById(R.id.web_view);
        progress = findViewById(R.id.progress);
        setupContainer = findViewById(R.id.setup_container);
        errorContainer = findViewById(R.id.error_container);
        setupError = findViewById(R.id.setup_error);
        errorTitle = findViewById(R.id.error_title);
        errorMessage = findViewById(R.id.error_message);
        addressInput = findViewById(R.id.address_input);

        configureWebView();

        Button connectButton = findViewById(R.id.connect_button);
        connectButton.setOnClickListener(view -> connect());
        addressInput.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO) {
                connect();
                return true;
            }
            return false;
        });

        findViewById(R.id.retry_button).setOnClickListener(view -> retry());
        findViewById(R.id.change_address_button).setOnClickListener(view -> changeAddress());

        String savedRoot = preferences.getString(PREF_SERVER_ROOT, null);
        if (savedRoot != null) {
            String checked = UrlPolicy.normalizeServerRoot(savedRoot);
            if (checked != null && checked.equals(savedRoot)) {
                normalizedRoot = checked;
                showWebView();
                loadRoot();
                return;
            }
            preferences.edit().remove(PREF_SERVER_ROOT).apply();
        }
        showSetup();
    }

    private void configureWebView() {
        // Even debug APKs cannot be inspected through chrome://inspect.
        WebView.setWebContentsDebuggingEnabled(false);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false);
        settings.setUserAgentString(settings.getUserAgentString() + " NihaixiaAndroid/0.4");
        settings.setDatabaseEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setLoadsImagesAutomatically(true);
        settings.setBlockNetworkImage(false);
        settings.setBlockNetworkLoads(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setGeolocationEnabled(false);
        settings.setSupportMultipleWindows(true);
        // All popups are intercepted by onCreateWindow and routed through UrlPolicy;
        // allowing script-opened windows keeps async device-code login on the system browser.
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setSaveFormData(false);

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, false);

        webView.setWebViewClient(new WorkbenchWebViewClient());
        webView.setWebChromeClient(new WorkbenchWebChromeClient());
        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                    String mimeType, long contentLength) {
                showPcDownloadNotice();
            }
        });
    }

    private void connect() {
        String input = addressInput.getText().toString().trim();
        String normalized = UrlPolicy.normalizeServerRoot(input);
        if (normalized == null) {
            setupError.setText(R.string.setup_invalid);
            setupError.setVisibility(View.VISIBLE);
            addressInput.requestFocus();
            return;
        }

        setupError.setVisibility(View.GONE);
        if (normalizedRoot != null && !normalizedRoot.equals(normalized)) {
            clearBrowsingState();
        }
        normalizedRoot = normalized;
        preferences.edit().putString(PREF_SERVER_ROOT, normalizedRoot).apply();
        addressInput.setText(normalizedRoot);
        hideKeyboard();

        showWebView();
        loadRoot();
        invalidateOptionsMenu();
    }

    private void retry() {
        hideErrorPanel();
        if (normalizedRoot == null) {
            showSetup();
            return;
        }
        loadRoot();
    }

    private void loadRoot() {
        if (normalizedRoot == null) {
            showSetup();
            return;
        }
        tlsFailureShown = false;
        hideErrorPanel();
        showWebView();
        progress.setProgress(0);
        progress.setVisibility(View.VISIBLE);
        webView.loadUrl(normalizedRoot + "/");
    }

    private void showWebView() {
        setupContainer.setVisibility(View.GONE);
        errorContainer.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        invalidateOptionsMenu();
    }

    private void showSetup() {
        setupError.setVisibility(View.GONE);
        errorContainer.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        setupContainer.setVisibility(View.VISIBLE);
        progress.setVisibility(View.GONE);
        if (normalizedRoot != null) {
            addressInput.setText(normalizedRoot);
        } else {
            addressInput.setText("");
        }
        invalidateOptionsMenu();
    }

    private void changeAddress() {
        clearBrowsingState();
        normalizedRoot = null;
        preferences.edit().remove(PREF_SERVER_ROOT).apply();
        tlsFailureShown = false;
        showSetup();
        addressInput.requestFocus();
    }

    private void clearBrowsingState() {
        if (webView != null) {
            webView.stopLoading();
            webView.clearHistory();
            webView.clearCache(true);
            webView.clearFormData();
        }
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.removeAllCookies(null);
        cookieManager.flush();
        WebStorage.getInstance().deleteAllData();
    }

    private boolean handleNavigation(Uri uri, boolean mainFrame) {
        if (uri == null) {
            return true;
        }
        String scheme = uri.getScheme();
        String url = uri.toString();

        if (DOWNLOAD_BLOCKED_SCHEME.equals(scheme)) {
            if (mainFrame) {
                progress.setVisibility(View.GONE);
                showPcDownloadNotice();
            }
            return true;
        }

        if (!"https".equals(scheme)) {
            if (mainFrame) {
                progress.setVisibility(View.GONE);
                if ("blob".equals(scheme) || "data".equals(scheme)
                        || "file".equals(scheme) || "content".equals(scheme)) {
                    showPcDownloadNotice();
                } else {
                    showBlockedLinkNotice();
                }
            }
            return true;
        }

        boolean sameOrigin = normalizedRoot != null
                && UrlPolicy.isSameOrigin(normalizedRoot, url);
        if (sameOrigin) {
            return false;
        }
        if (mainFrame) {
            progress.setVisibility(View.GONE);
            openExternalHttps(uri);
        }
        // External subframes are blocked; only the paired workbench origin may be framed.
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
        // No cookies, headers, or other app state are copied into the browser Intent.
    }

    private void showPcDownloadNotice() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.pc_download_title)
                .setMessage(R.string.pc_download_message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private void showBlockedLinkNotice() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.blocked_link_title)
                .setMessage(R.string.blocked_link_message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private void showNetworkError() {
        if (tlsFailureShown) {
            return;
        }
        showErrorPanel(getString(R.string.network_error_title),
                getString(R.string.network_error_message));
    }

    private void showTlsError() {
        if (tlsFailureShown) {
            return;
        }
        tlsFailureShown = true;
        showErrorPanel(getString(R.string.tls_error_title),
                getString(R.string.tls_error_message));
        new AlertDialog.Builder(this)
                .setTitle(R.string.tls_error_title)
                .setMessage(R.string.tls_error_message)
                .setPositiveButton(R.string.tls_error_ack, null)
                .show();
    }

    private void showErrorPanel(String title, String message) {
        if (webView != null) {
            webView.stopLoading();
        }
        progress.setVisibility(View.GONE);
        errorTitle.setText(title);
        errorMessage.setText(message);
        errorContainer.setVisibility(View.VISIBLE);
        errorContainer.bringToFront();
    }

    private void hideErrorPanel() {
        errorContainer.setVisibility(View.GONE);
    }

    private void hideKeyboard() {
        View focus = getCurrentFocus();
        if (focus == null) {
            return;
        }
        InputMethodManager manager = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (manager != null) {
            manager.hideSoftInputFromWindow(focus.getWindowToken(), 0);
        }
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.main_menu, menu);
        return true;
    }

    @Override
    public boolean onPrepareOptionsMenu(Menu menu) {
        boolean hasServer = normalizedRoot != null;
        MenuItem reload = menu.findItem(R.id.action_reload);
        if (reload != null) {
            reload.setVisible(hasServer && webView.getVisibility() == View.VISIBLE);
        }
        MenuItem change = menu.findItem(R.id.action_change_address);
        if (change != null) {
            change.setVisible(hasServer);
        }
        return super.onPrepareOptionsMenu(menu);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        int itemId = item.getItemId();
        if (itemId == R.id.action_reload) {
            loadRoot();
            return true;
        }
        if (itemId == R.id.action_change_address) {
            changeAddress();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (errorContainer.getVisibility() == View.VISIBLE) {
            hideErrorPanel();
            if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
                webView.goBack();
                return;
            }
            super.onBackPressed();
            return;
        }
        if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
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
        // The WebView and address field have saveEnabled=false, so page history,
        // form contents, session data and medical content are never persisted.
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.clearHistory();
            webView.clearCache(true);
        }
        if (isFinishing()) {
            CookieManager cookieManager = CookieManager.getInstance();
            cookieManager.removeAllCookies(null);
            cookieManager.flush();
            WebStorage.getInstance().deleteAllData();
        }
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private final class WorkbenchWebViewClient extends WebViewClient {

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
            if (url == null) {
                return true;
            }
            return handleNavigation(Uri.parse(url), true);
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            if (url != null && normalizedRoot != null
                    && UrlPolicy.isSameOrigin(normalizedRoot, url)) {
                tlsFailureShown = false;
                progress.setProgress(0);
                progress.setVisibility(View.VISIBLE);
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            progress.setVisibility(View.GONE);
            if (url != null && normalizedRoot != null
                    && UrlPolicy.isSameOrigin(normalizedRoot, url)) {
                view.evaluateJavascript(DOWNLOAD_GUARD_JS, null);
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request,
                WebResourceError error) {
            if (request != null && request.isForMainFrame()) {
                showNetworkError();
            }
        }

        @SuppressWarnings("deprecation")
        @Override
        public void onReceivedError(WebView view, int errorCode, String description,
                String failingUrl) {
            showNetworkError();
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            // Never call handler.proceed(); certificate errors must stop the connection.
            handler.cancel();
            showTlsError();
        }

        @Override
        public void onReceivedClientCertRequest(WebView view, ClientCertRequest request) {
            request.cancel();
        }

        @Override
        public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler,
                String host, String realm) {
            // The workbench uses its own HTTPS login page, not HTTP Basic auth.
            handler.cancel();
        }
    }

    private final class WorkbenchWebChromeClient extends WebChromeClient {

        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            if (progress.getVisibility() == View.VISIBLE) {
                progress.setProgress(newProgress);
            }
        }

        @Override
        public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture,
                Message resultMsg) {
            if (resultMsg == null || !(resultMsg.obj instanceof WebView.WebViewTransport)) {
                return false;
            }

            // target=_blank and window.open(...) are captured in a detached,
            // network-blocked WebView, then routed through the same policy.
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
                    // The popup may already have been torn down by WebView.
                }
            };
            popup.setWebViewClient(new WebViewClient() {
                private void route(WebView popupView, String url) {
                    if (url == null || url.isEmpty() || "about:blank".equals(url)
                            || routed[0]) {
                        return;
                    }
                    routed[0] = true;
                    if (UrlPolicy.isSameOrigin(normalizedRoot, url)) {
                        webView.loadUrl(url);
                    } else {
                        handleNavigation(Uri.parse(url), true);
                    }
                    popupView.postDelayed(destroyPopup, 500);
                }

                @Override
                public boolean shouldOverrideUrlLoading(WebView popupView,
                        WebResourceRequest request) {
                    route(popupView,
                            request == null || request.getUrl() == null
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
