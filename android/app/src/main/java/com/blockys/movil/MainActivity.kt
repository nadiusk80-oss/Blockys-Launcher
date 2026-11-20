package com.blockys.movil

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.content.FileProvider
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var web: WebView
    private val downloading = AtomicBoolean(false)

    @Volatile
    private var awaitingInstall = false

    private val pojavPackages = listOf("net.kdt.pojavlaunch", "net.kdt.pojavlaunch.debug")
    private val releasesApi =
        "https://api.github.com/repos/PojavLauncherTeam/PojavLauncher/releases/latest"
    private val releasesPage = "https://github.com/PojavLauncherTeam/PojavLauncher/releases/latest"
    private val playStore = "https://play.google.com/store/apps/details?id=net.kdt.pojavlaunch"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Bridge(), "Native")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.scheme == "file") {
                    return false
                }
                openExternal(request.url)
                return true
            }
        }
        web.loadUrl("file:///android_asset/index.html")
        setContentView(web)
    }

    private fun installedAny(): Boolean =
        pojavPackages.any { packageManager.getLaunchIntentForPackage(it) != null }

    private fun launchPojav(): Boolean {
        for (name in pojavPackages) {
            val intent = packageManager.getLaunchIntentForPackage(name) ?: continue
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            try {
                startActivity(intent)
                return true
            } catch (_: ActivityNotFoundException) {
            }
        }
        return false
    }

    private fun openExternal(uri: Uri): Boolean {
        val scheme = uri.scheme ?: return false
        if (scheme != "http" && scheme != "https") {
            return false
        }
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }

    private fun canInstallPackages(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls()

    private fun requestInstallPermission() {
        emit("error", "Activá «Instalar apps desconocidas» para Blockys Móvil y volvé a tocar Instalar.", 0.0)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val intent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:$packageName")
            )
            try {
                startActivity(intent)
            } catch (_: ActivityNotFoundException) {
                openExternal(Uri.parse("$releasesPage"))
            }
        }
    }

    inner class Bridge {
        @JavascriptInterface
        fun installed(): Boolean = installedAny()

        @JavascriptInterface
        fun launch(): Boolean {
            val ok = launchPojav()
            if (!ok) {
                emit("error", "No encontré PojavLauncher instalado.", 0.0)
            }
            return ok
        }

        @JavascriptInterface
        fun install(): Boolean {
            if (installedAny()) {
                launchPojav()
                return true
            }
            if (!canInstallPackages()) {
                requestInstallPermission()
                return true
            }
            if (!downloading.compareAndSet(false, true)) {
                return true
            }
            awaitingInstall = true
            thread(name = "pojav-install") { downloadAndInstall() }
            return true
        }

        @JavascriptInterface
        fun openPage(url: String) {
            openExternal(Uri.parse(url))
        }
    }

    private fun fetchJson(url: String): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 20000
        conn.readTimeout = 30000
        conn.setRequestProperty("Accept", "application/vnd.github+json")
        conn.setRequestProperty("User-Agent", "BlockysMovil/1.1.0")
        try {
            val code = conn.responseCode
            if (code != 200) {
                throw IllegalStateException("GitHub respondió $code")
            }
            return conn.inputStream.bufferedReader().use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    private fun downloadAndInstall() {
        try {
            emit("progress", "Buscando la última versión de PojavLauncher...", 1.0)
            val root = JSONObject(fetchJson(releasesApi))
            val assets = root.optJSONArray("assets")
                ?: throw IllegalStateException("La versión no trae archivos")
            var apkUrl: String? = null
            var apkSize = 0L
            for (i in 0 until assets.length()) {
                val asset = assets.getJSONObject(i)
                val name = asset.optString("name")
                if (name.equals("PojavLauncher.apk", ignoreCase = true)) {
                    apkUrl = asset.optString("browser_download_url")
                    apkSize = asset.optLong("size")
                    break
                }
                if (apkUrl == null && name.endsWith(".apk", ignoreCase = true)) {
                    apkUrl = asset.optString("browser_download_url")
                    apkSize = asset.optLong("size")
                }
            }
            val url = apkUrl?.takeIf { it.isNotEmpty() }
                ?: throw IllegalStateException("No encontré el APK de PojavLauncher")

            val dest = File(cacheDir, "PojavLauncher.apk")
            dest.delete()
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.instanceFollowRedirects = true
            conn.connectTimeout = 20000
            conn.readTimeout = 30000
            conn.setRequestProperty("User-Agent", "BlockysMovil/1.1.0")
            try {
                val code = conn.responseCode
                if (code != 200) {
                    throw IllegalStateException("La descarga falló (código $code)")
                }
                val total = if (apkSize > 0) apkSize else conn.contentLengthLong
                val megabytes = if (total > 0) total / (1024 * 1024) else 0L
                conn.inputStream.use { input ->
                    dest.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var done = 0L
                        var lastPercent = -1
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) {
                                break
                            }
                            output.write(buffer, 0, read)
                            done += read
                            if (total > 0) {
                                val percent = (done * 100 / total).toInt()
                                if (percent != lastPercent) {
                                    lastPercent = percent
                                    emit(
                                        "progress",
                                        "Descargando PojavLauncher ($megabytes MB, usá Wi-Fi)... $percent%",
                                        percent.toDouble()
                                    )
                                }
                            }
                        }
                    }
                }
            } finally {
                conn.disconnect()
            }
            if (dest.length() <= 0) {
                throw IllegalStateException("La descarga quedó vacía")
            }
            emit("progress", "Abriendo el instalador de PojavLauncher...", 100.0)
            openInstaller(dest)
        } catch (exc: Exception) {
            awaitingInstall = false
            emit("error", exc.message ?: "No se pudo instalar PojavLauncher", 0.0)
        } finally {
            downloading.set(false)
        }
    }

    private fun openInstaller(file: File) {
        runOnUiThread {
            val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
            val intent = Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            try {
                startActivity(intent)
                emit("done", "Tocá Instalar. Al volver, Blockys Móvil abre el juego solo.", 100.0)
            } catch (exc: ActivityNotFoundException) {
                awaitingInstall = false
                emit("error", "No hay instalador disponible. Probá desde Play Store.", 0.0)
            }
        }
    }

    private fun emit(type: String, message: String, value: Double) {
        val js = "window.nativeEvent && window.nativeEvent(" +
            "${JSONObject.quote(type)}, ${JSONObject.quote(message)}, $value)"
        runOnUiThread {
            if (!isFinishing) {
                web.evaluateJavascript(js, null)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (!::web.isInitialized) {
            return
        }
        val installed = installedAny()
        runOnUiThread {
            web.evaluateJavascript(
                "window.nativeEvent && window.nativeEvent('state', '', ${if (installed) 1 else 0})",
                null
            )
        }
        if (awaitingInstall && installed) {
            awaitingInstall = false
            emit("done", "PojavLauncher instalado. Abriendo el juego...", 100.0)
            launchPojav()
        }
    }

    @Deprecated("Android 13 uses the back callback, kept for older versions")
    override fun onBackPressed() {
        if (web.canGoBack()) {
            web.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }
}
