package com.signresponse.mobile.data

import android.content.Context

class SessionStore(context: Context) {
    private val preferences = context.getSharedPreferences("sign_response_session", Context.MODE_PRIVATE)

    var accessToken: String?
        get() = preferences.getString("access_token", null)
        set(value) = preferences.edit().putString("access_token", value).apply()

    var refreshToken: String?
        get() = preferences.getString("refresh_token", null)
        set(value) = preferences.edit().putString("refresh_token", value).apply()

    fun save(tokens: TokenPair) {
        preferences.edit()
            .putString("access_token", tokens.access_token)
            .putString("refresh_token", tokens.refresh_token)
            .apply()
    }

    fun saveDebugCredentials(email: String, password: String) {
        preferences.edit()
            .putString("debug_login_email", email)
            .putString("debug_login_password", password)
            .apply()
    }

    fun debugCredentials(): LoginRequest? {
        val email = preferences.getString("debug_login_email", null).orEmpty()
        val password = preferences.getString("debug_login_password", null).orEmpty()
        return if (email.isBlank() || password.isBlank()) null else LoginRequest(email, password)
    }

    fun clearTokens() {
        preferences.edit()
            .remove("access_token")
            .remove("refresh_token")
            .apply()
    }

}

