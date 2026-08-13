package com.signresponse.mobile.data

import com.google.gson.Gson
import retrofit2.HttpException
import java.io.IOException

class ReportRepository(
    private val api: ApiService = ApiClient.service,
    private val session: SessionStore,
) {
    suspend fun dashboard(): Pair<Identity, List<Report>> {
        val token = session.accessToken ?: throw IllegalStateException("Please sign in first.")
        val authorization = "Bearer $token"
        return api.me(authorization) to api.myReports(authorization)
    }
    suspend fun register(name: String, email: String, phone: String, password: String) {
        api.register(RegisterRequest(email.trim(), phone.trim().ifBlank { null }, password, name.trim()))
        login(email, password)
    }

    suspend fun login(email: String, password: String) {
        session.save(api.login(LoginRequest(email.trim(), password)))
    }

    suspend fun sendEmergency(
        title: String,
        description: String,
        latitude: Double,
        longitude: Double,
        accuracy: Float?,
    ): Report {
        val token = session.accessToken ?: throw IllegalStateException("Please sign in first.")
        return api.createReport(
            authorization = "Bearer $token",
            request = ReportRequest(
                category = title.trim().ifBlank { "Emergency Assistance" },
                description = description.trim().ifBlank {
                    "A deaf or hard-of-hearing user requested emergency assistance. Live sign-language video may be requested by the responding officer."
                },
                latitude = latitude,
                longitude = longitude,
                location_accuracy = accuracy,
                answers = mapOf("immediate_danger" to true),
            ),
        )
    }

    suspend fun startStream(reportId: String): StreamState {
        val token = session.accessToken ?: throw IllegalStateException("Please sign in first.")
        return api.startStream(reportId, "Bearer $token")
    }

    suspend fun recordStream(reportId: String): StreamState {
        val token = session.accessToken ?: throw IllegalStateException("Please sign in first.")
        return api.recordStream(reportId, "Bearer $token")
    }

    suspend fun stopStream(reportId: String) {
        val token = session.accessToken ?: return
        api.stopStream(reportId, "Bearer $token")
    }

    fun signedIn() = session.accessToken != null

    fun signOut() = session.clear()

    fun friendlyError(error: Throwable): String = when (error) {
        is HttpException -> {
            val detail = runCatching {
                Gson().fromJson(error.response()?.errorBody()?.string(), ErrorBody::class.java).detail
            }.getOrNull()
            detail ?: when (error.code()) {
                401 -> "Email or password is incorrect."
                409 -> "An account already exists with these details."
                422 -> "Please check the information you entered."
                else -> "The request could not be completed."
            }
        }
        is IOException -> "Connection lost. Check your internet and try again."
        else -> error.message ?: "Something went wrong. Please try again."
    }
}
