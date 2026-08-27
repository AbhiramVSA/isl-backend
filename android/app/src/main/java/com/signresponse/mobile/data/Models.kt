package com.signresponse.mobile.data

data class RegisterRequest(
    val email: String,
    val phone: String?,
    val password: String,
    val name: String,
)

data class LoginRequest(val email: String, val password: String)

data class Identity(
    val id: Int,
    val role: String,
    val name: String,
    val email: String,
    val phone: String? = null,
    val created_at: String? = null,
)

data class TokenPair(
    val access_token: String,
    val refresh_token: String,
    val token_type: String,
    val expires_in: Int,
)

data class ReportRequest(
    val category: String,
    val description: String,
    val latitude: Double,
    val longitude: Double,
    val location_accuracy: Float?,
    val answers: Map<String, Any> = emptyMap(),
)

data class Office(val id: Int, val name: String, val address: String)

data class Report(
    val public_id: String,
    val category: String,
    val description: String,
    val priority: String,
    val status: String,
    val created_at: String,
    val office: Office,
    val assigned_officer: Officer? = null,
)

data class Officer(val id: Int, val name: String, val badge_number: String, val rank: String?)

data class StreamState(
    val available: Boolean,
    val active: Boolean,
    val requested: Boolean,
    val recording: Boolean = false,
    val recording_available: Boolean = false,
    val viewer_url: String?,
    val access_token: String?,
)

data class TranscribedWord(
    val word: String,
    val confidence: Double,
)

data class SignTranscription(
    val transcript: String,
    val words: List<TranscribedWord>,
    val model: String,
)

data class ErrorBody(val detail: String?)
