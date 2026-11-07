package com.nihaixia.local;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class SecretPathPolicyTest {

    @Rule
    public TemporaryFolder temporary = new TemporaryFolder();

    @Test
    public void resolvesRelativeAndAbsolutePathsInsideTheRoot() throws Exception {
        Path root = temporary.getRoot().toPath().toRealPath();
        Files.createDirectories(root.resolve("secrets"));
        Path relative = SecretPathPolicy.resolve(root, "secrets/api-key.bin");
        assertEquals(root.resolve("secrets/api-key.bin"), relative.toAbsolutePath().normalize());
        Path absolute = SecretPathPolicy.resolve(root,
                root.resolve("secrets/other.bin").toString());
        assertTrue(absolute.startsWith(root));
    }

    @Test
    public void rejectsEscapesRootsAndNulBytes() throws Exception {
        Path root = temporary.newFolder("runtime").toPath().toRealPath();
        Path outside = temporary.newFolder("outside").toPath().toRealPath();
        assertRejected(root, "../outside/secret");
        assertRejected(root, "../../secret");
        assertRejected(root, outside.resolve("secret").toString());
        assertRejected(root, "");
        assertRejected(root, null);
        assertRejected(root, "a\0b");
        try {
            SecretPathPolicy.resolve(root, ".");
            fail("root itself must not be a secret path");
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }

    @Test
    public void rejectsSymbolicLinkComponentsWhenSupported() throws Exception {
        Path root = temporary.newFolder("runtime").toPath().toRealPath();
        Path outside = temporary.newFolder("linked-outside").toPath().toRealPath();
        Path link = root.resolve("link");
        try {
            Files.createSymbolicLink(link, outside);
        } catch (UnsupportedOperationException | IOException | SecurityException notSupported) {
            return; // Windows without developer mode: the explicit checks still exist.
        }
        assertRejected(root, "link/key.bin");
    }

    private static void assertRejected(Path root, String path) throws Exception {
        try {
            SecretPathPolicy.resolve(root, path);
            fail("expected rejection: " + path);
        } catch (IllegalArgumentException expected) {
            assertFalse(expected.getMessage().contains("secret-value"));
        }
    }
}
