package com.nihaixia.local;

import android.webkit.JavascriptInterface;

/**
 * The only JavaScript interface in the app. It exposes a single request method that
 * schedules a local Python dispatch; filesystem, secret and HTTP services are not
 * reachable from JavaScript.
 */
public final class LocalBridge {

    public interface Dispatcher {
        void dispatch(String id, String method, String path, String body);
    }

    private final Dispatcher dispatcher;

    public LocalBridge(Dispatcher dispatcher) {
        this.dispatcher = dispatcher;
    }

    @JavascriptInterface
    public void request(String id, String method, String path, String body) {
        dispatcher.dispatch(id, method, path, body);
    }
}