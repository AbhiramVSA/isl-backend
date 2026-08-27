package com.signresponse.mobile.data

import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface ApiService {
    @GET("auth/me")
    suspend fun me(@Header("Authorization") authorization: String): Identity

    @GET("users/me/reports")
    suspend fun myReports(@Header("Authorization") authorization: String): List<Report>
    @POST("auth/users/register")
    suspend fun register(@Body request: RegisterRequest): Identity

    @POST("auth/users/login")
    suspend fun login(@Body request: LoginRequest): TokenPair

    @POST("reports")
    suspend fun createReport(
        @Header("Authorization") authorization: String,
        @Body request: ReportRequest,
    ): Report

    @POST("reports/{id}/location")
    suspend fun updateLocation(
        @Path("id") reportId: String,
        @Header("Authorization") authorization: String,
        @Body request: Map<String, Any>,
    )

    @POST("reports/{id}/stream/start")
    suspend fun startStream(
        @Path("id") reportId: String,
        @Header("Authorization") authorization: String,
    ): StreamState

    @POST("reports/{id}/stream/record")
    suspend fun recordStream(
        @Path("id") reportId: String,
        @Header("Authorization") authorization: String,
    ): StreamState

    @POST("reports/{id}/stream/stop")
    suspend fun stopStream(
        @Path("id") reportId: String,
        @Header("Authorization") authorization: String,
    ): StreamState

    @POST("reports/{id}/transcription")
    suspend fun transcribeRecording(
        @Path("id") reportId: String,
        @Header("Authorization") authorization: String,
    ): SignTranscription
}
