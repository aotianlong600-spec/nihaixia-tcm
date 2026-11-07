package com.nihaixia.local;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

public class BridgePolicyTest {

    @Test
    public void acceptsBoundedLocalRequestShapes() {
        assertTrue(BridgePolicy.validId("a1b2-c3d4:e5"));
        assertEquals("GET", BridgePolicy.normalizeMethod(" get "));
        assertEquals("/consultations/abc/messages?x=1",
                BridgePolicy.normalizePath("/consultations/abc/messages?x=1"));
        assertEquals("", BridgePolicy.normalizeBody(null));
        assertEquals("", BridgePolicy.normalizeBody(""));
        assertEquals("{}", BridgePolicy.normalizeBody("{}"));
    }

    @Test
    public void rejectsTraversalSchemesAndOversizedInputs() {
        assertFalse(BridgePolicy.validId(""));
        assertFalse(BridgePolicy.validId("bad id"));
        assertFalse(BridgePolicy.validId("bad\nid"));
        assertFalse(BridgePolicy.validId(new String(new char[129]).replace('\0', 'a')));

        assertRejectedMethod("CONNECT");
        assertRejectedMethod("TRACE");
        assertRejectedMethod("");

        assertRejectedPath("consultations");
        assertRejectedPath("//evil");
        assertRejectedPath("/../../etc/passwd");
        assertRejectedPath("/a\\b");
        assertRejectedPath("/a\nb");
        assertRejectedPath("https://example.com/");

        StringBuilder tooLarge = new StringBuilder(BridgePolicy.MAX_BODY_CHARS + 1);
        for (int i = 0; i <= BridgePolicy.MAX_BODY_CHARS; i++) {
            tooLarge.append('x');
        }
        try {
            BridgePolicy.normalizeBody(tooLarge.toString());
            fail("expected oversized body rejection");
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }

    private static void assertRejectedMethod(String method) {
        try {
            BridgePolicy.normalizeMethod(method);
            fail("expected method rejection: " + method);
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }

    private static void assertRejectedPath(String path) {
        try {
            BridgePolicy.normalizePath(path);
            fail("expected path rejection: " + path);
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }
}
