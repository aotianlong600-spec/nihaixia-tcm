package com.nihaixia.local;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

public class HttpUrlPolicyTest {

    @Test
    public void allowsSystemValidatedHttpsToAnyProvider() {
        assertEquals("api.example.com", HttpUrlPolicy.validate("https://api.example.com/v1/chat").getHost());
        assertEquals("203.0.113.9", HttpUrlPolicy.validate("https://203.0.113.9:8443/v1").getHost());
    }

    @Test
    public void cleartextIsLoopbackOnly() {
        assertEquals("127.0.0.1", HttpUrlPolicy.validate("http://127.0.0.1:11434/v1").getHost());
        assertEquals("localhost", HttpUrlPolicy.validate("http://localhost:11434/v1").getHost());
        HttpUrlPolicy.validate("http://[::1]:11434/v1");
        assertTrue(HttpUrlPolicy.isLoopbackHost("::1"));
        assertTrue(HttpUrlPolicy.isLoopbackHost("127.2.3.4"));

        assertRejected("http://192.168.1.20:8766/v1");
        assertRejected("http://10.0.0.1/v1");
        assertRejected("http://example.com/v1");
    }

    @Test
    public void rejectsCredentialedAndNonHttpUrls() {
        assertRejected("https://user@example.com/v1");
        assertRejected("https://user:pass@example.com/v1");
        assertRejected("file:///data/data/secret");
        assertRejected("ftp://example.com/file");
        assertRejected("javascript:alert(1)");
        assertRejected("https:///no-host");
        assertRejected("https://example.com:0/");
        assertRejected("https://example.com:99999/");
        assertRejected("https://example.com/\nInjected: value");
        assertRejected("https://example.com/\\evil");
        assertRejected(null);
        assertRejected("");
    }

    @Test
    public void loopbackDetectionIsStrict() {
        assertFalse(HttpUrlPolicy.isLoopbackHost("127.0.0"));
        assertFalse(HttpUrlPolicy.isLoopbackHost("127.0.0.256"));
        assertFalse(HttpUrlPolicy.isLoopbackHost("127.0.0.a"));
        assertFalse(HttpUrlPolicy.isLoopbackHost("example.com"));
        assertFalse(HttpUrlPolicy.isLoopbackHost(null));
    }

    private static void assertRejected(String url) {
        try {
            HttpUrlPolicy.validate(url);
            fail("expected rejection: " + url);
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }
}