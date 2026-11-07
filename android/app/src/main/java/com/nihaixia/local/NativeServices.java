package com.nihaixia.local;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Private services called only from Python (never exposed as a JavaScript interface).
 *
 * <p>HTTP uses normal {@link HttpURLConnection} system-CA validation, rejects URLs
 * containing credentials, refuses to follow redirects, bounds request/response sizes
 * and supports cancellation. Secrets are AES-GCM encrypted with an AndroidKeyStore key
 * and written atomically under the configured runtime root; no secret is logged or
 * returned through the WebView bridge.</p>
 */
public final class NativeServices {

    private static final String KEY_ALIAS = "nihaixia-local-secrets-v1";
    private static final String MAGIC = "NXL1";
    private static final int MAX_TIMEOUT_MS = 120_000;
    private static final int MAX_REQUEST_BYTES = 4 * 1024 * 1024;
    private static final int MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
    private static final int MAX_SECRET_BYTES = 1024 * 1024;
    private static final int MAX_HEADERS = 100;
    private static final List<String> FORBIDDEN_HEADERS = Arrays.asList(
            "host", "content-length", "connection", "transfer-encoding",
            "upgrade", "trailer", "proxy-connection", "expect");

    private static final ConcurrentHashMap<String, Pending> PENDING = new ConcurrentHashMap<>();
    private static volatile Path runtimeRoot;

    private NativeServices() {
    }

    /** Sets the single allowed private runtime root. Called before Python starts. */
    public static void configure(String dataDir) {
        if (dataDir == null || dataDir.isEmpty()) {
            throw new IllegalArgumentException("data directory is required");
        }
        try {
            Path root = Paths.get(dataDir).toAbsolutePath().normalize();
            Files.createDirectories(root);
            root.toRealPath();
            runtimeRoot = root;
        } catch (IOException exception) {
            throw new IllegalStateException("unable to prepare the private runtime directory");
        }
    }

    /**
     * Executes one HTTP request and returns {@code {status,headers,body}}. A status of
     * 0 with an {@code error} code means the request failed or was refused locally.
     */
    public static String http(String method, String url, String headersJson, String body,
            String requestId, int timeoutMs) {
        String id = requestId == null ? "" : requestId;
        Pending pending = null;
        HttpURLConnection connection = null;
        try {
            URI uri = HttpUrlPolicy.validate(url);
            String verb = method == null ? "" : method.trim().toUpperCase(Locale.ROOT);
            if (!Arrays.asList("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD").contains(verb)) {
                return error("unsupported_method");
            }
            int timeout = timeoutMs <= 0 ? 30_000 : Math.min(timeoutMs, MAX_TIMEOUT_MS);
            connection = (HttpURLConnection) uri.toURL().openConnection();
            connection.setRequestMethod(verb);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setConnectTimeout(timeout);
            connection.setReadTimeout(timeout);
            connection.setRequestProperty("User-Agent", "NihaixiaLocal/0.5");

            if (!applyHeaders(connection, headersJson)) {
                connection.disconnect();
                return error("invalid_headers");
            }

            pending = new Pending(connection);
            Pending previous = PENDING.put(id, pending);
            if (previous != null) {
                previous.cancel();
            }
            if (pending.cancelled) {
                return error("cancelled");
            }

            if (body != null && !body.isEmpty() && !"GET".equals(verb) && !"HEAD".equals(verb)) {
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                if (bytes.length > MAX_REQUEST_BYTES) {
                    return error("request_too_large");
                }
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }

            int status = connection.getResponseCode();
            if (pending.cancelled) {
                return error("cancelled");
            }
            if (status >= 300 && status < 400) {
                return error("redirect_blocked");
            }

            JSONObject headers = responseHeaders(connection);
            String responseBody = "";
            if (!"HEAD".equals(verb)) {
                InputStream stream = status >= 400
                        ? connection.getErrorStream() : connection.getInputStream();
                if (stream != null) {
                    byte[] bytes = readBounded(stream, MAX_RESPONSE_BYTES);
                    if (bytes == null) {
                        return error("response_too_large");
                    }
                    responseBody = new String(bytes, StandardCharsets.UTF_8);
                }
            }
            JSONObject envelope = new JSONObject();
            envelope.put("status", status);
            envelope.put("headers", headers);
            envelope.put("body", responseBody);
            return envelope.toString();
        } catch (IllegalArgumentException exception) {
            return error("invalid_url");
        } catch (IOException exception) {
            return error(pending != null && pending.cancelled ? "cancelled" : "network_error");
        } catch (JSONException exception) {
            return error("invalid_headers");
        } catch (RuntimeException exception) {
            return error("http_failed");
        } finally {
            if (pending != null) {
                PENDING.remove(id, pending);
            }
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    /** Disconnects a pending request; safe for unknown ids. */
    public static void cancelHttp(String id) {
        if (id == null) {
            return;
        }
        Pending pending = PENDING.remove(id);
        if (pending != null) {
            pending.cancel();
        }
    }

    /** Returns the decrypted secret, or null when no such private file exists. */
    public static String readSecret(String path) {
        try {
            Path file = SecretPathPolicy.resolve(requireRoot(), path);
            if (!Files.isRegularFile(file)) {
                return null;
            }
            long size = Files.size(file);
            if (size <= 0 || size > MAX_SECRET_BYTES) {
                throw new IllegalStateException("unable to read secret");
            }
            byte[] data = Files.readAllBytes(file);
            if (data.length < MAGIC.length() + 4 + 12 || !MAGIC.equals(
                    new String(data, 0, MAGIC.length(), StandardCharsets.US_ASCII))) {
                throw new IllegalStateException("unable to read secret");
            }
            ByteBuffer buffer = ByteBuffer.wrap(data, MAGIC.length(), data.length - MAGIC.length());
            int nonceLength = buffer.getInt();
            if (nonceLength < 12 || nonceLength > 32 || buffer.remaining() <= nonceLength) {
                throw new IllegalStateException("unable to read secret");
            }
            byte[] nonce = new byte[nonceLength];
            buffer.get(nonce);
            byte[] ciphertext = new byte[buffer.remaining()];
            buffer.get(ciphertext);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, loadKey(false), new GCMParameterSpec(128, nonce));
            byte[] plain = cipher.doFinal(ciphertext);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("unable to read secret");
        } catch (IllegalArgumentException exception) {
            throw new IllegalStateException("unable to read secret");
        } catch (Exception exception) {
            throw new IllegalStateException("unable to read secret");
        }
    }

    /** Encrypts and atomically replaces a secret file inside the runtime root. */
    public static void writeSecret(String path, String value) {
        if (value == null) {
            throw new IllegalArgumentException("secret value is required");
        }
        byte[] plain = value.getBytes(StandardCharsets.UTF_8);
        if (plain.length > 64 * 1024) {
            throw new IllegalArgumentException("secret value too large");
        }
        Path temporary = null;
        try {
            Path file = SecretPathPolicy.resolve(requireRoot(), path);
            Path parent = file.getParent();
            if (parent == null) {
                throw new IllegalStateException("unable to write secret");
            }
            Files.createDirectories(parent);
            file = SecretPathPolicy.resolve(requireRoot(), path);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, loadKey(true));
            byte[] nonce = cipher.getIV();
            byte[] ciphertext = cipher.doFinal(plain);
            byte[] magic = MAGIC.getBytes(StandardCharsets.US_ASCII);
            ByteBuffer buffer = ByteBuffer.allocate(magic.length + 4 + nonce.length + ciphertext.length);
            buffer.put(magic);
            buffer.putInt(nonce.length);
            buffer.put(nonce);
            buffer.put(ciphertext);
            byte[] payload = buffer.array();
            if (payload.length > MAX_SECRET_BYTES) {
                throw new IllegalStateException("unable to write secret");
            }

            temporary = Files.createTempFile(parent, ".secret-", ".tmp");
            try (FileChannel channel = FileChannel.open(temporary,
                    StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING)) {
                ByteBuffer bufferToWrite = ByteBuffer.wrap(payload);
                while (bufferToWrite.hasRemaining()) {
                    channel.write(bufferToWrite);
                }
                channel.force(true);
            }
            try {
                Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException exception) {
                Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING);
            }
            temporary = null;
        } catch (IOException exception) {
            throw new IllegalStateException("unable to write secret");
        } catch (IllegalArgumentException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new IllegalStateException("unable to write secret");
        } finally {
            if (temporary != null) {
                try {
                    Files.deleteIfExists(temporary);
                } catch (IOException ignored) {
                    // The temp file is app-private and contains ciphertext only.
                }
            }
        }
    }

    static Path requireRoot() {
        Path root = runtimeRoot;
        if (root == null) {
            throw new IllegalStateException("NativeServices is not configured");
        }
        return root;
    }

    private static SecretKey loadKey(boolean create) throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        }
        if (!create) {
            throw new IllegalStateException("secret key is missing");
        }
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }

    private static boolean applyHeaders(HttpURLConnection connection, String headersJson)
            throws JSONException {
        JSONObject headers = new JSONObject(
                headersJson == null || headersJson.isEmpty() ? "{}" : headersJson);
        int count = 0;
        Iterator<String> keys = headers.keys();
        while (keys.hasNext()) {
            if (++count > MAX_HEADERS) {
                return false;
            }
            String name = keys.next();
            if (!validHeaderName(name) || FORBIDDEN_HEADERS.contains(name.toLowerCase(Locale.ROOT))) {
                return false;
            }
            Object raw = headers.get(name);
            String value;
            if (raw instanceof JSONArray) {
                JSONArray values = (JSONArray) raw;
                List<String> parts = new ArrayList<>();
                for (int i = 0; i < values.length() && i < 20; i++) {
                    parts.add(String.valueOf(values.get(i)));
                }
                value = String.join(", ", parts);
            } else {
                value = String.valueOf(raw);
            }
            if (!validHeaderValue(value)) {
                return false;
            }
            connection.setRequestProperty(name, value);
        }
        return true;
    }

    private static JSONObject responseHeaders(HttpURLConnection connection) throws JSONException {
        JSONObject result = new JSONObject();
        int count = 0;
        for (Map.Entry<String, List<String>> entry : connection.getHeaderFields().entrySet()) {
            String name = entry.getKey();
            if (name == null || !validHeaderName(name)) {
                continue;
            }
            if (++count > MAX_HEADERS) {
                break;
            }
            List<String> values = entry.getValue();
            String value = values == null ? "" : String.join(", ", values);
            if (value.length() > 4096) {
                value = value.substring(0, 4096);
            }
            result.put(name, value);
        }
        return result;
    }

    private static boolean validHeaderName(String name) {
        if (name == null || name.isEmpty() || name.length() > 128) {
            return false;
        }
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            boolean token = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                    || (c >= '0' && c <= '9')
                    || "!#$%&'*+-.^_`|~".indexOf(c) >= 0;
            if (!token) {
                return false;
            }
        }
        return true;
    }

    private static boolean validHeaderValue(String value) {
        if (value == null || value.length() > 4096) {
            return false;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '\r' || c == '\n' || c == '\0') {
                return false;
            }
        }
        return true;
    }

    private static byte[] readBounded(InputStream stream, int limit) throws IOException {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int total = 0;
            int read;
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > limit) {
                    return null;
                }
                output.write(buffer, 0, read);
            }
            return output.toByteArray();
        }
    }

    private static String error(String code) {
        try {
            JSONObject envelope = new JSONObject();
            envelope.put("status", 0);
            envelope.put("headers", new JSONObject());
            envelope.put("body", "");
            envelope.put("error", code);
            return envelope.toString();
        } catch (JSONException exception) {
            return "{\"status\":0,\"headers\":{},\"body\":\"\",\"error\":\"http_failed\"}";
        }
    }

    private static final class Pending {
        final HttpURLConnection connection;
        volatile boolean cancelled;

        Pending(HttpURLConnection connection) {
            this.connection = connection;
        }

        void cancel() {
            cancelled = true;
            connection.disconnect();
        }
    }
}
