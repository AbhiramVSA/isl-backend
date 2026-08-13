package com.signresponse.mobile.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Colors = lightColorScheme(
    primary = Color(0xFF153B50),
    onPrimary = Color.White,
    secondary = Color(0xFF256F83),
    error = Color(0xFFC63F37),
    background = Color(0xFFF5F7F8),
    surface = Color.White,
    onSurface = Color(0xFF17272E),
)

@Composable
fun SignResponseTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Colors, typography = Typography(), content = content)
}

