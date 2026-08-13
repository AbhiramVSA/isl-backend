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

    fun clear() = preferences.edit().clear().apply()
}

