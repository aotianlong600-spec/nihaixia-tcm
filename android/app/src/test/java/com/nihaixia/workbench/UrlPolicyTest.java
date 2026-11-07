package com.nihaixia.local;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Navigation, bridge-path and PDF/original token policy. */
public class UrlPolicyTest {

    private static final String SHA =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    @Test
    public void acceptsOnlyTheBundledAppOriginInsideTheWebView() {
        assertTrue(UrlPolicy.isAppAssetUrl(UrlPolicy.INDEX_URL));
        assertTrue(UrlPolicy.isAppAssetUrl(UrlPolicy.APP_ORIGIN + "/assets/app.js?v=1"));
        assertTrue(UrlPolicy.isAppAssetUrl(UrlPolicy.APP_ORIGIN + "/nested/page.html#top"));

        assertFalse(UrlPolicy.isAppAssetUrl("http://appassets.androidplatform.net/index.html"));
        assertFalse(UrlPolicy.isAppAssetUrl("https://appassets.androidplatform.net.evil.example/"));
        assertFalse(UrlPolicy.isAppAssetUrl("https://user@appassets.androidplatform.net/"));
        assertFalse(UrlPolicy.isAppAssetUrl("https://appassets.androidplatform.net:444/"));
        assertFalse(UrlPolicy.isAppAssetUrl("javascript:alert(1)"));
        assertFalse(UrlPolicy.isAppAssetUrl("file:///data/data/app/index.html"));
        assertFalse(UrlPolicy.isAppAssetUrl(null));
    }

    @Test
    public void rejectsTraversalAndUnsafeAssetPaths() {
        assertFalse(UrlPolicy.isSafeAssetPath("/../secret"));
        assertFalse(UrlPolicy.isSafeAssetPath("/a/./b"));
        assertFalse(UrlPolicy.isSafeAssetPath("/a\\b"));
        assertFalse(UrlPolicy.isSafeAssetPath("relative/path"));
        assertFalse(UrlPolicy.isSafeAssetPath("/bad\npath"));
        assertTrue(UrlPolicy.isSafeAssetPath("/"));
        assertTrue(UrlPolicy.isSafeAssetPath("/assets/a.js"));
        assertFalse(UrlPolicy.isAppAssetUrl(UrlPolicy.APP_ORIGIN + "/%2e%2e/secret"));
    }

    @Test
    public void externalHttpsIsOnlyOpenedOutsideTheWebView() {
        assertTrue(UrlPolicy.isExternalHttps("https://example.com/path?q=1"));
        assertTrue(UrlPolicy.isExternalHttps("https://203.0.113.7:8443/"));
        assertFalse(UrlPolicy.isExternalHttps("http://example.com/"));
        assertFalse(UrlPolicy.isExternalHttps("https://user:pass@example.com/"));
        assertFalse(UrlPolicy.isExternalHttps(UrlPolicy.APP_ORIGIN + "/index.html"));
        assertFalse(UrlPolicy.isExternalHttps("intent://example.com/"));
        assertFalse(UrlPolicy.isExternalHttps("https:///missing-host"));
        assertFalse(UrlPolicy.isExternalHttps("https://example.com/\\evil"));
    }

    @Test
    public void parsesOnlyCanonicalPdfImagePaths() {
        assertEquals(SHA, UrlPolicy.pdfSha("/local/pdf/" + SHA + "/12.png"));
        assertEquals(12, UrlPolicy.pdfPage("/local/pdf/" + SHA + "/12.png"));
        assertEquals(1, UrlPolicy.pdfPage("/local/pdf/" + SHA + "/1.png"));

        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA.toUpperCase() + "/1.png"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/0.png"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/01.png"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/-1.png"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/1.jpg"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/1.png/extra"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/not-a-hash/1.png"));
        assertNull(UrlPolicy.pdfSha("/local/pdf/" + SHA + "/1234567890.png"));
        assertNull(UrlPolicy.pdfSha(null));
        assertEquals(-1, UrlPolicy.pdfPage("/local/pdf/" + SHA + "/00.png"));
    }

    @Test
    public void parsesOnlyExactOriginalLinks() {
        assertEquals(SHA, UrlPolicy.originalSha("/local/original/" + SHA));
        assertNull(UrlPolicy.originalSha("/local/original/" + SHA + "/"));
        assertNull(UrlPolicy.originalSha("/local/original/" + SHA + ".pdf"));
        assertNull(UrlPolicy.originalSha("/local/original/../../etc/passwd"));
        assertNull(UrlPolicy.originalSha("https://appassets.androidplatform.net/local/original/" + SHA));
    }

    @Test
    public void exposesSchemeSafely() {
        assertEquals("https", UrlPolicy.scheme("https://example.com"));
        assertEquals("javascript", UrlPolicy.scheme("javascript:alert(1)"));
        assertEquals("", UrlPolicy.scheme("not a url"));
        assertEquals("", UrlPolicy.scheme(null));
    }
}
