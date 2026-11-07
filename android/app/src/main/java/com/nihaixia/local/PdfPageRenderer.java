package com.nihaixia.local;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.os.ParcelFileDescriptor;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.util.regex.Pattern;

/** Renders one physical PDF page to PNG using an identical size bound to the desktop app. */
public final class PdfPageRenderer {

    private static final Pattern SHA = Pattern.compile("[0-9a-f]{64}");
    private static final double MAX_SCALE = 1.5;
    private static final double MAX_WIDTH = 2000.0;
    private static final double MAX_HEIGHT = 2800.0;

    private PdfPageRenderer() {
    }

    public static byte[] renderPng(File runtimeRoot, String sha, int physicalPage)
            throws IOException {
        if (!validSha(sha) || physicalPage < 1) {
            throw new IllegalArgumentException("invalid original page");
        }
        File original = OriginalFiles.pdf(runtimeRoot, sha);
        if (!original.isFile()) {
            throw new IOException("original is missing");
        }
        try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(
                original, ParcelFileDescriptor.MODE_READ_ONLY);
                PdfRenderer renderer = new PdfRenderer(descriptor)) {
            if (physicalPage > renderer.getPageCount()) {
                throw new IOException("physical page does not exist");
            }
            PdfRenderer.Page page = renderer.openPage(physicalPage - 1);
            try {
                int width = page.getWidth();
                int height = page.getHeight();
                if (width <= 0 || height <= 0) {
                    throw new IOException("PDF page size is invalid");
                }
                double scale = Math.min(MAX_SCALE,
                        Math.min(MAX_WIDTH / width, MAX_HEIGHT / height));
                int bitmapWidth = Math.max(1, (int) Math.floor(width * scale));
                int bitmapHeight = Math.max(1, (int) Math.floor(height * scale));
                Bitmap bitmap = Bitmap.createBitmap(
                        bitmapWidth, bitmapHeight, Bitmap.Config.ARGB_8888);
                try {
                    Canvas canvas = new Canvas(bitmap);
                    canvas.drawColor(Color.WHITE);
                    page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                    ByteArrayOutputStream output = new ByteArrayOutputStream();
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                        throw new IOException("unable to encode PDF page");
                    }
                    return output.toByteArray();
                } finally {
                    bitmap.recycle();
                }
            } finally {
                page.close();
            }
        }
    }

    public static boolean validSha(String sha) {
        return sha != null && SHA.matcher(sha).matches();
    }
}