package com.nihaixia.local;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Pure navigation and asset-path policy for the standalone offline container.
 *
 * <p>The WebView may only navigate inside the bundled {@code appassets} origin. Any other
 * HTTPS URL is handed to the system browser; {@code javascript:}, {@code file:},
 * {@code content:}, {@code data:}, {@code blob:} and every other scheme are blocked.
 * PDF/original paths are validated here so rendering never receives an arbitrary path.</p>
 *
 * <p>No Android dependency: these rules are unit tested on the JVM.</p>
 */
public final class UrlPolicy {

    public static final String APP_HOST = "appassets.androidplatform.net";
    public static final String APP_ORIGIN = "https://" + APP_HOST;
    public static final String INDEX_URL = APP_ORIGIN + "/index.html";
    public static final String PDF_PREFIX = "/local/pdf/";
    public static final String ORIGINAL_PREFIX = "/local/original/";

    private static final Pattern PDF_PATH = Pattern.compile(
            "^/local/pdf/([0-9a-f]{64})/([0-9]+)\\.png$");
    private static final Pattern ORIGINAL_PATH = Pattern.compile(
            "^/local/original/([0-9a-f]{64})$");

    private UrlPolicy() {
    }

    /** True only for the fixed bundled origin, with no user info and no traversal. */
    public static boolean isAppAssetUrl(String value) {
        URI uri = parse(value);
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme())) {
            return false;
        }
        if (uri.getRawUserInfo() != null || uri.getHost() == null
                || !APP_HOST.equalsIgnoreCase(uri.getHost()) || uri.getPort() != -1) {
            return false;
        }
        return isSafeAssetPath(uri.getPath());
    }

    /** External HTTPS links must be well formed and must never carry user info. */
    public static boolean isExternalHttps(String value) {
        URI uri = parse(value);
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme())) {
            return false;
        }
        if (uri.getRawUserInfo() != null || uri.getHost() == null
                || uri.getHost().isEmpty()) {
            return false;
        }
        return !APP_HOST.equalsIgnoreCase(uri.getHost());
    }

    /** Returns the lowercase 64-hex original token for a PDF image path, or null. */
    public static String pdfSha(String path) {
        Matcher matcher = PDF_PATH.matcher(path == null ? "" : path);
        if (!matcher.matches() || pdfPage(path) < 1) {
            return null;
        }
        return matcher.group(1);
    }

    /** Returns the canonical positive physical page number, or -1. */
    public static int pdfPage(String path) {
        Matcher matcher = PDF_PATH.matcher(path == null ? "" : path);
        if (!matcher.matches()) {
            return -1;
        }
        String digits = matcher.group(2);
        if (digits.isEmpty() || digits.length() > 9
                || (digits.length() > 1 && digits.charAt(0) == '0')) {
            return -1;
        }
        try {
            int page = Integer.parseInt(digits);
            return page >= 1 ? page : -1;
        } catch (NumberFormatException exception) {
            return -1;
        }
    }

    /** Returns the lowercase 64-hex original token for an original-file link, or null. */
    public static String originalSha(String path) {
        Matcher matcher = ORIGINAL_PATH.matcher(path == null ? "" : path);
        return matcher.matches() ? matcher.group(1) : null;
    }

    /** True when the URL path stays inside the asset root (no dot segments/backslashes). */
    public static boolean isSafeAssetPath(String path) {
        if (path == null || !path.startsWith("/") || path.length() > 2048) {
            return false;
        }
        for (int i = 0; i < path.length(); i++) {
            char c = path.charAt(i);
            if (c == '\\' || c < 0x20 || c == 0x7f) {
                return false;
            }
        }
        for (String segment : path.split("/", -1)) {
            if (".".equals(segment) || "..".equals(segment)) {
                return false;
            }
        }
        return true;
    }

    /** Lowercase URL scheme without allocating for malformed input. */
    public static String scheme(String value) {
        URI uri = parse(value);
        return uri == null || uri.getScheme() == null
                ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
    }

    private static URI parse(String value) {
        if (value == null || value.isEmpty() || value.length() > 8192) {
            return null;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c <= 0x20 || c == 0x7f || c == '\\') {
                return null;
            }
        }
        try {
            return new URI(value);
        } catch (URISyntaxException exception) {
            return null;
        }
    }
}
