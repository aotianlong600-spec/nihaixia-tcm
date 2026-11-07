package com.nihaixia.local;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.core.app.ActivityScenario;
import android.webkit.WebView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONTokener;

import com.chaquo.python.Python;
import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Device smoke test: the bundled pack starts without a PC or network, and the local
 * session dispatcher answers through the shared Python runtime.
 *
 * <p>Requires the parent build to have copied the packaged knowledge assets.</p>
 */
@RunWith(AndroidJUnit4.class)
public class StandaloneRuntimeSmokeTest {

    @Test
    public void bundledKnowledgeAndSessionWorkOffline() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        String initialized = PythonBootstrap.initialize(context);
        JSONObject envelope = new JSONObject(initialized);
        assertEquals(200, envelope.getInt("status"));
        assertTrue(envelope.getJSONObject("body").getBoolean("ready"));

        String session = Python.getInstance().getModule("app.mobile_api")
                .callAttr("dispatch", "GET", "/session", "").toString();
        JSONObject sessionEnvelope = new JSONObject(session);
        assertEquals(200, sessionEnvelope.getInt("status"));
        JSONObject body = sessionEnvelope.getJSONObject("body");
        assertTrue(body.getBoolean("standalone"));
        assertEquals("android", body.getString("platform"));
        JSONObject overview = request("GET", "/personal/overview", "");
        JSONObject counts = packCounts(context);
        assertEquals(counts.getInt("source_catalog"), overview.getInt("sources"));
        assertEquals(counts.getInt("pages"), overview.getInt("pdf_pages"));
        assertTrue(overview.getInt("formula_count") > 0);
        JSONObject created = request("POST", "/consultations", "{\"intake\":{\"chief_complaint\":\"仅用于设备离线测试\",\"symptoms\":[\"发热\",\"怕冷\"]}}");
        request("GET", "/consultations/" + created.getString("id") + "/context", "");
        String sha = firstPdfId();
        if (sha != null) {
            request("GET", "/library/sources/" + sha + "/units/1", "");
            byte[] image = PdfPageRenderer.renderPng(PythonBootstrap.dataDir(context), sha, 1);
            assertTrue(image.length > 8);
            assertEquals((byte) 0x89, image[0]);
        }
    }

    private JSONObject packCounts(Context context) throws Exception {
        File manifest = new File(PythonBootstrap.packDir(context), "manifest.json");
        return new JSONObject(new String(Files.readAllBytes(manifest.toPath()), StandardCharsets.UTF_8))
                .getJSONObject("tables");
    }

    private String firstPdfId() throws Exception {
        org.json.JSONArray sources = request("GET", "/library/sources", "").getJSONArray("items");
        for (int index = 0; index < sources.length(); index++) {
            JSONObject source = sources.getJSONObject(index);
            if ("pdf".equals(source.getString("format"))) return source.getString("id");
        }
        return null;
    }

    private JSONObject request(String method, String path, String body) throws Exception {
        JSONObject response = new JSONObject(Python.getInstance().getModule("app.mobile_api")
                .callAttr("dispatch", method, path, body).toString());
        assertEquals(response.toString(), 200, response.getInt("status"));
        return response.getJSONObject("body");
    }

    @Test
    public void secretsUseDeviceKeystoreWithoutPlaintextFiles() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        PythonBootstrap.initialize(context);
        File secret = new File(PythonBootstrap.dataDir(context),"model-keys/instrumentation-key.dpapi");
        String value = "synthetic-keystore-roundtrip-only";
        try {
            NativeServices.writeSecret(secret.getAbsolutePath(),value);
            assertEquals(value,NativeServices.readSecret(secret.getAbsolutePath()));
            assertTrue(!new String(Files.readAllBytes(secret.toPath()),StandardCharsets.UTF_8).contains(value));
        } finally {
            Files.deleteIfExists(secret.toPath());
        }
    }

    @Test
    public void bundledFrontendAndPdfRouteLoadWithoutAComputer() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        PythonBootstrap.initialize(context);
        JSONObject counts = packCounts(context);
        String sources = "资料 " + counts.getInt("source_catalog");
        String pages = "原书页 " + counts.getInt("pages");
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            AtomicReference<String> text = new AtomicReference<>("");
            long deadline = System.currentTimeMillis()+60000;
            while (System.currentTimeMillis()<deadline) {
                CountDownLatch read = new CountDownLatch(1);
                scenario.onActivity(activity -> ((WebView)activity.findViewById(R.id.web_view))
                    .evaluateJavascript("document.body ? document.body.innerText : ''", value -> {
                        try { text.set(String.valueOf(new JSONTokener(value).nextValue())); }
                        catch (Exception ignored) { text.set(""); }
                        read.countDown();
                    }));
                read.await(5,TimeUnit.SECONDS);
                if (text.get().contains(sources) && text.get().contains(pages)) break;
                Thread.sleep(250);
            }
            assertTrue("Bundled UI did not finish local initialization: "+text.get(),
                text.get().contains(sources) && text.get().contains(pages));
            String sha = firstPdfId();
            if (sha == null) return;
            scenario.onActivity(activity -> ((WebView)activity.findViewById(R.id.web_view)).evaluateJavascript(
                "(()=>{const i=new Image();i.onload=()=>document.body.dataset.pdfProbe='ok';i.onerror=()=>document.body.dataset.pdfProbe='error';i.src="
                    + JSONObject.quote("/local/pdf/" + sha + "/1.png") + ";})()", null));
            AtomicReference<String> image = new AtomicReference<>("");
            deadline=System.currentTimeMillis()+15000;
            while (System.currentTimeMillis()<deadline) {
                CountDownLatch read = new CountDownLatch(1);
                scenario.onActivity(activity -> ((WebView)activity.findViewById(R.id.web_view)).evaluateJavascript(
                    "document.body.dataset.pdfProbe || ''",value->{image.set(value);read.countDown();}));
                read.await(3,TimeUnit.SECONDS);
                if (image.get().contains("ok") || image.get().contains("error")) break;
                Thread.sleep(200);
            }
            assertTrue("Native PDF route failed: "+image.get(),image.get().contains("ok"));
        }
    }
}
