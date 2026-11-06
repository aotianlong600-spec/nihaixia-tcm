package com.nihaixia.workbench;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Security contract for the only server address the app may store and load.
 *
 * <p>These tests intentionally describe the policy before the implementation exists.</p>
 */
public class UrlPolicyTest {

    @Test
    public void acceptsPrivateIpv4HttpsRootsWithExplicitPort() {
        assertEquals("https://10.0.0.1:8766", UrlPolicy.normalizeServerRoot("https://10.0.0.1:8766"));
        assertEquals("https://10.255.255.255:443", UrlPolicy.normalizeServerRoot("https://10.255.255.255:443"));
        assertEquals("https://172.16.0.1:8766", UrlPolicy.normalizeServerRoot("https://172.16.0.1:8766"));
        assertEquals("https://172.31.255.255:8443", UrlPolicy.normalizeServerRoot("https://172.31.255.255:8443"));
        assertEquals("https://192.168.0.1:8766", UrlPolicy.normalizeServerRoot("https://192.168.0.1:8766"));
        assertEquals("https://192.168.255.254:65535", UrlPolicy.normalizeServerRoot("https://192.168.255.254:65535"));
    }

    @Test
    public void acceptsAndNormalizesASingleTrailingSlash() {
        assertEquals("https://192.168.1.20:8766",
                UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766/"));
    }

    @Test
    public void rejectsPublicLoopbackLinkLocalAndReservedAddresses() {
        assertNull(UrlPolicy.normalizeServerRoot("https://127.0.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://8.8.8.8:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://1.1.1.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://0.0.0.0:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://169.254.1.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://224.0.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://255.255.255.255:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://172.15.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://172.32.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.169.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://11.0.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://100.64.0.1:8766"));
    }

    @Test
    public void rejectsNonHttpsAndMissingScheme() {
        assertNull(UrlPolicy.normalizeServerRoot("http://192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("HTTP://192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("HTTPS://192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("ws://192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("javascript:alert(1)"));
    }

    @Test
    public void rejectsHostnamesAndLocalhost() {
        assertNull(UrlPolicy.normalizeServerRoot("https://localhost:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://server.local:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://example.com:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20.nip.io:8766"));
    }

    @Test
    public void rejectsFancyOrAmbiguousIpv4Forms() {
        assertNull(UrlPolicy.normalizeServerRoot("https://010.0.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.01:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.001:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://0x0a.0.0.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.1.5:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.1.:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.256:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.-1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0.+1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10.0.0. 1:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://10..0.1:8766"));
    }

    @Test
    public void rejectsUserInfoQueryFragmentAndAnyPath() {
        assertNull(UrlPolicy.normalizeServerRoot("https://user@192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://user:pass@192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766/?next=/"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766/app"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766//"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766/#fragment"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766?x=1"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766#x"));
    }

    @Test
    public void rejectsPortsThatAreMissingEmptyOutOfRangeOrAmbiguous() {
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:0"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:65536"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:999999"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:-1"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:abc"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766x"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:08766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:1:2"));
    }

    @Test
    public void rejectsWhitespaceControlCharactersAndNullOrEmptyInput() {
        assertNull(UrlPolicy.normalizeServerRoot(null));
        assertNull(UrlPolicy.normalizeServerRoot(""));
        assertNull(UrlPolicy.normalizeServerRoot("   "));
        assertNull(UrlPolicy.normalizeServerRoot(" https://192.168.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766 "));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766\n"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168\t.1.20:8766"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766\\evil"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20:8766@evil.example"));
    }

    @Test
    public void httpsDefaultPortMayBeOmittedByBrowserNavigation() {
        String root = "https://192.168.1.20:443";
        assertEquals(root, UrlPolicy.normalizeServerRoot(root));
        assertTrue(UrlPolicy.isSameOrigin(root, "https://192.168.1.20/"));
        assertTrue(UrlPolicy.isSameOrigin(root, "https://192.168.1.20/app?x=1"));
        assertFalse(UrlPolicy.isSameOrigin("https://192.168.1.20:8766", "https://192.168.1.20/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://user@192.168.1.20/"));
        assertNull(UrlPolicy.normalizeServerRoot("https://192.168.1.20"));
    }

    @Test
    public void sameOriginRequiresExactHttpsSchemeHostAndPort() {
        String root = "https://192.168.1.20:8766";
        assertTrue(UrlPolicy.isSameOrigin(root, "https://192.168.1.20:8766/"));
        assertTrue(UrlPolicy.isSameOrigin(root, "https://192.168.1.20:8766/app?x=1#y"));

        assertFalse(UrlPolicy.isSameOrigin(root, "http://192.168.1.20:8766/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://192.168.1.20:443/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://192.168.1.21:8766/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://192.168.1.20:8766.evil.example/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://user@192.168.1.20:8766/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://evil.example/https://192.168.1.20:8766/"));
        assertFalse(UrlPolicy.isSameOrigin(root, "javascript:alert(1)"));
        assertFalse(UrlPolicy.isSameOrigin(root, "https://192.168.1.20:8766\\@evil.example/"));
        assertFalse(UrlPolicy.isSameOrigin(root, null));
        assertFalse(UrlPolicy.isSameOrigin(null, "https://192.168.1.20:8766/"));
    }
}
