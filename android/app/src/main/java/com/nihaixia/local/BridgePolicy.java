package com.nihaixia.local;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;

/** Validation for the only JavaScript-to-Java request shape that exists. */
public final class BridgePolicy {

    public static final int MAX_BODY_CHARS = 1_000_000;
    private static final List<String> METHODS =
            Arrays.asList("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD");

    private BridgePolicy() {
    }

    public static boolean validId(String id) {
        if (id == null || id.isEmpty() || id.length() > 128) {
            return false;
        }
        for (int i = 0; i < id.length(); i++) {
            char c = id.charAt(i);
            boolean allowed = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                    || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == ':' || c == '-';
            if (!allowed) {
                return false;
            }
        }
        return true;
    }

    public static String normalizeMethod(String method) {
        if (method == null) {
            throw new IllegalArgumentException("invalid method");
        }
        String value = method.trim().toUpperCase(Locale.ROOT);
        if (!METHODS.contains(value)) {
            throw new IllegalArgumentException("unsupported method");
        }
        return value;
    }

    /**
     * Local API paths start with one slash and may carry a query. Traversal, control
     * characters, backslashes and scheme-like values are rejected before Python runs.
     */
    public static String normalizePath(String path) {
        if (path == null || path.isEmpty() || path.length() > 2048 || path.charAt(0) != '/') {
            throw new IllegalArgumentException("invalid path");
        }
        for (int i = 0; i < path.length(); i++) {
            char c = path.charAt(i);
            if (c == '\\' || c < 0x20 || c == 0x7f) {
                throw new IllegalArgumentException("invalid path");
            }
        }
        if (path.startsWith("//") || path.contains("..")) {
            throw new IllegalArgumentException("invalid path");
        }
        return path;
    }

    public static String normalizeBody(String body) {
        if (body == null || body.isEmpty()) {
            return "";
        }
        if (body.length() > MAX_BODY_CHARS) {
            throw new IllegalArgumentException("body too large");
        }
        return body;
    }
}
