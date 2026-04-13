package com.paymentapproval.factoryapp

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var cameraImageUri: Uri? = null

    private val filePickerLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val parsedResults = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        val finalResults = when {
            result.resultCode != Activity.RESULT_OK -> null
            !parsedResults.isNullOrEmpty() -> parsedResults
            cameraImageUri != null -> arrayOf(cameraImageUri!!)
            else -> null
        }
        filePathCallback?.onReceiveValue(finalResults)
        filePathCallback = null
        cameraImageUri = null
    }

    private fun createImageUri(): Uri {
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val imageFile = File.createTempFile("bill_${timeStamp}_", ".jpg", cacheDir)
        return FileProvider.getUriForFile(this, "${packageName}.fileprovider", imageFile)
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.allowFileAccess = true
        webView.settings.allowContentAccess = true
        webView.settings.cacheMode = WebSettings.LOAD_NO_CACHE
        webView.settings.userAgentString = webView.settings.userAgentString + " FactoryApprovalAndroid/1.0"
        webView.clearCache(true)
        webView.clearHistory()

        webView.webViewClient = WebViewClient()
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback

                val galleryIntent = Intent(Intent.ACTION_GET_CONTENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "image/*"
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
                }

                val cameraIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).also { intent ->
                    cameraImageUri = createImageUri()
                    intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraImageUri)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                }

                val chooserIntent = Intent(Intent.ACTION_CHOOSER).apply {
                    putExtra(Intent.EXTRA_INTENT, galleryIntent)
                    putExtra(Intent.EXTRA_TITLE, "Upload bill image")
                    putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(cameraIntent))
                }

                filePickerLauncher.launch(chooserIntent)
                return true
            }
        }

        webView.loadUrl("https://paymentapproval.onrender.com")
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
