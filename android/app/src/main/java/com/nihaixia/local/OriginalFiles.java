package com.nihaixia.local;

import android.webkit.MimeTypeMap;

import java.io.File;
import java.io.IOException;
import java.util.Locale;

/** Resolves only registered hash-named originals under the private data directory. */
public final class OriginalFiles {

    private OriginalFiles() {
    }

    public static File pdf(File runtimeRoot, String sha) throws IOException {
        if (!PdfPageRenderer.validSha(sha)) {
            throw new IllegalArgumentException("invalid original hash");
        }
        File originals = new File(runtimeRoot, "originals").getCanonicalFile();
        File file = new File(originals, sha + ".pdf").getCanonicalFile();
        if (!originals.equals(file.getParentFile())) {
            throw new IOException("original path leaves the originals directory");
        }
        return file;
    }

    public static String mimeType(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        String extension = dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.ROOT);
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
        return mime == null ? "application/octet-stream" : mime;
    }
}