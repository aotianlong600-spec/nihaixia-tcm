package com.nihaixia.local;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * Resolves secret file names strictly inside the configured private runtime root.
 *
 * <p>Absolute paths outside the root, {@code ..} escapes, the root itself, NUL characters
 * and every symbolic-link component are rejected. Pure JVM code so the escape rules are
 * unit tested without a device.</p>
 */
public final class SecretPathPolicy {

    private SecretPathPolicy() {
    }

    public static Path resolve(Path root, String requested) throws IOException {
        if (root == null) {
            throw new IllegalArgumentException("runtime root is not configured");
        }
        if (requested == null || requested.isEmpty() || requested.length() > 1024) {
            throw new IllegalArgumentException("invalid secret path");
        }
        if (requested.indexOf('\0') >= 0) {
            throw new IllegalArgumentException("invalid secret path");
        }

        Path rootAbsolute = root.toAbsolutePath().normalize();
        Path rootReal = rootAbsolute.toRealPath();
        if (!Files.isDirectory(rootReal, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("invalid runtime root");
        }

        Path candidate = Paths.get(requested);
        if (!candidate.isAbsolute()) {
            candidate = rootReal.resolve(candidate);
        }
        candidate = candidate.toAbsolutePath().normalize();
        // Android's trusted app directory may have /data/user/0 and /data/data aliases.
        if (candidate.startsWith(rootAbsolute)) {
            candidate = rootReal.resolve(rootAbsolute.relativize(candidate)).normalize();
        }
        if (!candidate.startsWith(rootReal) || candidate.equals(rootReal)) {
            throw new IllegalArgumentException("secret path leaves runtime root");
        }

        Path existing = candidate;
        while (existing != null && !Files.exists(existing, LinkOption.NOFOLLOW_LINKS)) {
            existing = existing.getParent();
        }
        if (existing == null || !existing.startsWith(rootReal)) {
            throw new IllegalArgumentException("secret path leaves runtime root");
        }

        Path cursor = rootReal;
        for (Path component : rootReal.relativize(existing)) {
            cursor = cursor.resolve(component);
            if (Files.isSymbolicLink(cursor)) {
                throw new IllegalArgumentException("secret path uses a symbolic link");
            }
        }
        Path real = existing.toRealPath();
        if (!real.startsWith(rootReal)) {
            throw new IllegalArgumentException("secret path leaves runtime root");
        }
        if (Files.isSymbolicLink(candidate)) {
            throw new IllegalArgumentException("secret path uses a symbolic link");
        }
        return candidate;
    }
}
