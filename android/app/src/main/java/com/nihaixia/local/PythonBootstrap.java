package com.nihaixia.local;

import android.content.Context;
import android.content.res.AssetManager;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Copies the bundled knowledge pack into app-private storage, starts Chaquopy and calls
 * {@code app.mobile_api.initialize(data_dir, knowledge_dir)}. Existing runtime files are
 * never deleted; bundled files that already exist are left untouched.
 */
public final class PythonBootstrap {

    private static volatile PyObject mobileApi;
    private static File stagingDir;

    private PythonBootstrap() {
    }

    public static File runtimeDir(Context context) {
        return new File(context.getFilesDir(), "runtime");
    }

    public static File dataDir(Context context) {
        return new File(runtimeDir(context), "data");
    }

    public static File packDir(Context context) {
        try (InputStream input = context.getAssets().open("knowledge/manifest.json")) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            StringBuilder version = new StringBuilder();
            for (byte value : digest.digest()) version.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
            return new File(new File(runtimeDir(context), "knowledge"), version.toString());
        } catch (IOException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("knowledge manifest unavailable", exception);
        }
    }

    /** Runs the complete bootstrap off the caller's thread and returns the Python envelope. */
    public static synchronized String initialize(Context context) throws Exception {
        File data = dataDir(context);
        File pack = packDir(context);
        stagingDir = new File(runtimeDir(context), ".bootstrap-staging");
        if (!stagingDir.isDirectory() && !stagingDir.mkdirs()) {
            throw new IOException("unable to create bootstrap staging directory");
        }
        if (!data.isDirectory() && !data.mkdirs()) {
            throw new IOException("unable to create the private data directory");
        }
        if (!pack.isDirectory() && !pack.mkdirs()) {
            throw new IOException("unable to create the private knowledge directory");
        }
        NativeServices.configure(data.getAbsolutePath());
        copyAssetTree(context.getAssets(), "knowledge", pack, 0);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(context));
        }
        PyObject api = Python.getInstance().getModule("app.mobile_api");
        mobileApi = api;
        String result = api.callAttr(
                "initialize", data.getAbsolutePath(), pack.getAbsolutePath()).toString();
        JSONObject envelope = new JSONObject(result);
        JSONObject body = envelope.optJSONObject("body");
        if (envelope.optInt("status", 0) != 200 || body == null
                || !body.optBoolean("ready", false)) {
            throw new IOException("bundled knowledge pack did not become ready: "
                    + (body == null ? "no response body" : body.optJSONObject("diagnostic")));
        }
        return result;
    }

    static PyObject requireMobileApi() {
        PyObject api = mobileApi;
        if (api == null) {
            throw new IllegalStateException("local runtime is not ready");
        }
        return api;
    }

    private static int copyAssetTree(AssetManager assets, String assetPath, File destination,
            int depth) throws IOException {
        if (depth > 16) {
            throw new IOException("asset tree is too deep");
        }
        String[] children = assets.list(assetPath);
        if (children == null) {
            throw new IOException("knowledge assets are missing");
        }
        if (children.length == 0) {
            return copyAssetFile(assets, assetPath, destination);
        }
        if (!destination.isDirectory() && !destination.mkdirs()) {
            throw new IOException("unable to create knowledge directory");
        }
        int copied = 0;
        String base = destination.getCanonicalPath() + File.separator;
        for (String name : children) {
            if (name == null || name.isEmpty() || name.contains("/") || name.contains("\\")
                    || ".".equals(name) || "..".equals(name)) {
                throw new IOException("unsafe asset name");
            }
            File child = new File(destination, name);
            if (!child.getCanonicalPath().startsWith(base)) {
                throw new IOException("asset path leaves destination");
            }
            String childAsset = assetPath + "/" + name;
            String[] grandChildren = assets.list(childAsset);
            if (grandChildren != null && grandChildren.length > 0) {
                copied += copyAssetTree(assets, childAsset, child, depth + 1);
            } else {
                copied += copyAssetFile(assets, childAsset, child);
            }
        }
        return copied;
    }

    private static int copyAssetFile(AssetManager assets, String assetPath, File destination)
            throws IOException {
        if (destination.isFile()) {
            return 0;
        }
        File parent = destination.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) {
            throw new IOException("unable to create knowledge directory");
        }
        File temporary = File.createTempFile(".asset-", ".tmp", stagingDir);
        boolean moved = false;
        try {
            try (InputStream input = assets.open(assetPath);
                    FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[64 * 1024];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    output.write(buffer, 0, read);
                }
                output.getFD().sync();
            }
            try {
                Files.move(temporary.toPath(), destination.toPath(),
                        StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException exception) {
                Files.move(temporary.toPath(), destination.toPath(),
                        StandardCopyOption.REPLACE_EXISTING);
            }
            moved = true;
        } finally {
            if (!moved) {
                Files.deleteIfExists(temporary.toPath());
            }
        }
        return 1;
    }
}
