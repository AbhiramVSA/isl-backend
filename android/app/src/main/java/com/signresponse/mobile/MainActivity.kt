package com.signresponse.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.signresponse.mobile.ui.SignResponseApp
import com.signresponse.mobile.ui.theme.SignResponseTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SignResponseTheme { SignResponseApp() }
        }
    }
}

