package com.lueyoyo.skydaily

import android.app.Activity
import android.os.Bundle
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

class MainActivity : Activity() {
    private lateinit var web: WebView

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        web = WebView(this)
        setContentView(web)
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = true
            cacheMode = WebSettings.LOAD_DEFAULT
            mediaPlaybackRequiresUserGesture = false
            userAgentString = userAgentString + " SkyDailyApp/1.0"
        }
        web.webViewClient = WebViewClient()
        if (b != null) web.restoreState(b)
        else web.loadUrl("https://lueyoyo1-afk.github.io/sky-daily/")
    }

    override fun onSaveInstanceState(o: Bundle) {
        super.onSaveInstanceState(o)
        web.saveState(o)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
