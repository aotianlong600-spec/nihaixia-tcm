package com.nihaixia.local;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/**
 * URL rules for the internal (non-JavaScript) HTTP service.
 *
 * <p>HTTPS is allowed to any configured provider and relies on normal system CA
 * validation. Cleartext HTTP is restricted to loopback. URLs containing credentials
 * are always rejected; redirects are rejected by the caller so bearer tokens can never
 * be replayed to another host.</p>
 */
public final class HttpUrlPolicy {

    private HttpUrlPolicy() {
    }

    public static URI validate(String url) {
        if (url == null || url.isEmpty() || url.length() > 8192) {
            throw new IllegalArgumentException("invalid URL");
        }
        for (int i = 0; i < url.length(); i++) {
            char c = url.charAt(i);
            if (c <= 0x20 || c == 0x7f || c == '\\') {
                throw new IllegalArgumentException("invalid URL");
            }
        }
        final URI uri;
        try {
            uri = new URI(url);
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("invalid URL");
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!"https".equals(scheme) && !"http".equals(scheme)) {
            throw new IllegalArgumentException("unsupported URL scheme");
        }
        if (uri.getRawUserInfo() != null || uri.getHost() == null || uri.getHost().isEmpty()) {
            throw new IllegalArgumentException("credentialed or host-less URL");
        }
        int port = uri.getPort();
        if (port == 0 || port > 65535) {
            throw new IllegalArgumentException("invalid URL port");
        }
        if ("http".equals(scheme) && !isLoopbackHost(uri.getHost())) {
            throw new IllegalArgumentException("cleartext HTTP is loopback-only");
        }
        return uri;
    }

    public static boolean isLoopbackHost(String host) {
        if (host == null) {
            return false;
        }
        String value = host.toLowerCase(Locale.ROOT);
        if (value.startsWith("[") && value.endsWith("]")) {
            value = value.substring(1, value.length() - 1);
        }
        if ("::1".equals(value) || "localhost".equals(value)) {
            return true;
        }
        if (!value.startsWith("127.")) {
            return false;
        }
        String[] parts = value.split("\\.", -1);
        if (parts.length != 4) {
            return false;
        }
        for (int i = 1; i < 4; i++) {
            if (parts[i].isEmpty() || parts[i].length() > 3) {
                return false;
            }
            for (int j = 0; j < parts[i].length(); j++) {
                if (!Character.isDigit(parts[i].charAt(j))) {
                    return false;
                }
            }
            if (Integer.parseInt(parts[i]) > 255) {
                return false;
            }
        }
        return true;
    }
}