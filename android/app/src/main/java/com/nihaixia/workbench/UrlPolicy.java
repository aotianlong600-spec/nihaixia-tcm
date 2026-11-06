package com.nihaixia.workbench;

/**
 * Validates the only network address this container is allowed to persist or load.
 *
 * <p>Policy: an explicit {@code https://} root URL whose host is a canonical, dotted-quad
 * RFC 1918 IPv4 address (10/8, 172.16/12, 192.168/16) and whose explicit port is in
 * 1..65535. Hostnames, localhost, public/reserved addresses, non-canonical IPv4 spellings,
 * user info, paths, queries and fragments are rejected.</p>
 *
 * <p>This class deliberately has no Android dependency so the policy can be unit tested
 * on the JVM before it is used by the WebView activity.</p>
 */
public final class UrlPolicy {

    private static final String SCHEME_PREFIX = "https://";

    private UrlPolicy() {
    }

    /**
     * Returns the normalized server root ({@code https://a.b.c.d:port}) or {@code null}
     * when the input is not an allowed private LAN root.
     */
    public static String normalizeServerRoot(String input) {
        if (input == null || input.isEmpty() || hasUnsafeCharacters(input)) {
            return null;
        }
        if (!input.startsWith(SCHEME_PREFIX)) {
            return null;
        }

        String rest = input.substring(SCHEME_PREFIX.length());
        if (rest.isEmpty()) {
            return null;
        }

        int authorityEnd = rest.length();
        for (int i = 0; i < rest.length(); i++) {
            char c = rest.charAt(i);
            if (c == '/' || c == '?' || c == '#') {
                authorityEnd = i;
                break;
            }
        }

        String suffix = rest.substring(authorityEnd);
        // A single trailing slash is tolerated; any path, query or fragment is not.
        if (!suffix.isEmpty() && !"/".equals(suffix)) {
            return null;
        }

        String authority = rest.substring(0, authorityEnd);
        HostAndPort parsed = parseHostAndPort(authority);
        if (parsed == null || !isPrivateIpv4(parsed.host)) {
            return null;
        }
        return SCHEME_PREFIX + parsed.host + ":" + parsed.port;
    }

    /**
     * True only when {@code candidateUrl} is HTTPS and has exactly the same canonical
     * host and effective port as the normalized server root. Paths, queries and fragments
     * are allowed for in-app navigation; user info and ambiguous authorities are not.
     */
    public static boolean isSameOrigin(String normalizedServerRoot, String candidateUrl) {
        if (normalizedServerRoot == null || candidateUrl == null) {
            return false;
        }
        String expected = normalizeServerRoot(normalizedServerRoot);
        if (expected == null || !expected.equals(normalizedServerRoot)) {
            return false;
        }
        if (candidateUrl.isEmpty() || hasUnsafeCharacters(candidateUrl)
                || !candidateUrl.startsWith(SCHEME_PREFIX)) {
            return false;
        }

        String rest = candidateUrl.substring(SCHEME_PREFIX.length());
        int authorityEnd = rest.length();
        for (int i = 0; i < rest.length(); i++) {
            char c = rest.charAt(i);
            if (c == '/' || c == '?' || c == '#') {
                authorityEnd = i;
                break;
            }
        }
        String authority = rest.substring(0, authorityEnd);
        // Browsers omit HTTPS's default port during URL serialization.
        HostAndPort candidate = parseHostAndPort(authority.indexOf(':') < 0 ? authority + ":443" : authority);
        if (candidate == null) {
            return false;
        }

        String expectedAuthority = expected.substring(SCHEME_PREFIX.length());
        HostAndPort root = parseHostAndPort(expectedAuthority);
        return root != null
                && root.host.equals(candidate.host)
                && root.port == candidate.port;
    }

    /** Strict canonical dotted-quad check plus RFC 1918 range membership. */
    public static boolean isPrivateIpv4(String host) {
        if (host == null || hasUnsafeCharacters(host)) {
            return false;
        }
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) {
            return false;
        }
        int[] octets = new int[4];
        for (int i = 0; i < parts.length; i++) {
            String part = parts[i];
            if (part.isEmpty() || part.length() > 3) {
                return false;
            }
            if (part.length() > 1 && part.charAt(0) == '0') {
                return false; // no octal-looking or zero-padded forms
            }
            for (int j = 0; j < part.length(); j++) {
                char c = part.charAt(j);
                if (c < '0' || c > '9') {
                    return false;
                }
            }
            octets[i] = Integer.parseInt(part);
            if (octets[i] > 255) {
                return false;
            }
        }
        if (octets[0] == 10) {
            return true;
        }
        if (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) {
            return true;
        }
        return octets[0] == 192 && octets[1] == 168;
    }

    private static HostAndPort parseHostAndPort(String authority) {
        if (authority == null || authority.isEmpty() || authority.indexOf('@') >= 0) {
            return null;
        }
        int firstColon = authority.indexOf(':');
        if (firstColon <= 0 || firstColon != authority.lastIndexOf(':')) {
            return null;
        }
        String host = authority.substring(0, firstColon);
        String portText = authority.substring(firstColon + 1);
        if (portText.isEmpty() || portText.length() > 5) {
            return null;
        }
        if (portText.length() > 1 && portText.charAt(0) == '0') {
            return null;
        }
        for (int i = 0; i < portText.length(); i++) {
            char c = portText.charAt(i);
            if (c < '0' || c > '9') {
                return null;
            }
        }
        int port = Integer.parseInt(portText);
        if (port < 1 || port > 65535) {
            return null;
        }
        return new HostAndPort(host, port);
    }

    private static boolean hasUnsafeCharacters(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c <= 0x20 || c == 0x7f || c == '\\') {
                return true;
            }
        }
        return false;
    }

    private static final class HostAndPort {
        final String host;
        final int port;

        HostAndPort(String host, int port) {
            this.host = host;
            this.port = port;
        }
    }
}
