package com.signresponse.mobile.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.signresponse.mobile.data.Report
import com.signresponse.mobile.data.ReportRepository
import com.signresponse.mobile.data.Identity
import com.signresponse.mobile.data.SessionStore
import com.signresponse.mobile.data.LiveVideoPublisher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import io.livekit.android.renderer.SurfaceViewRenderer

data class AppUiState(
    val signedIn: Boolean = false,
    val loading: Boolean = false,
    val message: String? = null,
    val error: String? = null,
    val submittedReport: Report? = null,
    val streaming: Boolean = false,
    val recording: Boolean = false,
    val profile: Identity? = null,
    val reports: List<Report> = emptyList(),
)

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = ReportRepository(session = SessionStore(application))
    private val videoPublisher = LiveVideoPublisher(application)
    private val _state = MutableStateFlow(AppUiState(signedIn = repository.signedIn()))
    val state: StateFlow<AppUiState> = _state.asStateFlow()

    fun login(email: String, password: String, onSuccess: () -> Unit) = runRequest {
        repository.login(email, password)
        val (profile, reports) = repository.dashboard()
        _state.value = AppUiState(signedIn = true, message = "Signed in successfully.", profile = profile, reports = reports)
        onSuccess()
    }

    fun register(name: String, email: String, phone: String, password: String, onSuccess: () -> Unit) = runRequest {
        repository.register(name, email, phone, password)
        val (profile, reports) = repository.dashboard()
        _state.value = AppUiState(signedIn = true, message = "Account created successfully.", profile = profile, reports = reports)
        onSuccess()
    }

    fun loadDashboard() = runRequest {
        val (profile, reports) = repository.dashboard()
        _state.value = _state.value.copy(signedIn = true, profile = profile, reports = reports)
    }

    fun sendEmergency(title: String, description: String, latitude: Double, longitude: Double, accuracy: Float?) = runRequest {
        val report = repository.sendEmergency(title, description, latitude, longitude, accuracy)
        _state.value = _state.value.copy(
            signedIn = true,
            message = "Emergency sent to ${report.office.name}. Starting your camera…",
            submittedReport = report,
        )
        val stream = repository.startStream(report.public_id)
        val url = stream.viewer_url ?: error("The video service did not provide a connection address.")
        val token = stream.access_token ?: error("The video service did not provide access.")
        _state.value = _state.value.copy(
            signedIn = true,
            message = "Starting camera and connecting officers…",
            submittedReport = report,
            streaming = true,
        )
        try {
            videoPublisher.start(url, token)
        } catch (error: Throwable) {
            videoPublisher.stop()
            _state.value = _state.value.copy(streaming = false, recording = false)
            throw IllegalStateException(
                "The report was sent, but live video could not connect. Start the video service and try again.",
                error,
            )
        }
        _state.value = _state.value.copy(message = "Camera is live for responding officers.")
        val recording = repository.recordStream(report.public_id).recording
        _state.value = _state.value.copy(
            signedIn = true,
            message = if (recording) "Camera is live and the emergency video is being saved." else "Camera is live for responding officers.",
            submittedReport = report,
            streaming = true,
            recording = recording,
        )
    }

    fun endVideo() = runRequest {
        val reportId = _state.value.submittedReport?.public_id ?: return@runRequest
        videoPublisher.stop()
        repository.stopStream(reportId)
        _state.value = _state.value.copy(
            message = "Video ended. Your emergency report remains open for officers.",
            streaming = false,
            recording = false,
        )
    }

    fun attachPreview(renderer: SurfaceViewRenderer) = videoPublisher.attachPreview(renderer)

    fun detachPreview(renderer: SurfaceViewRenderer) = videoPublisher.detachPreview(renderer)

    fun signOut(onSuccess: () -> Unit) {
        viewModelScope.launch { videoPublisher.stop() }
        repository.signOut()
        _state.value = AppUiState()
        onSuccess()
    }

    fun clearMessages() {
        _state.value = _state.value.copy(message = null, error = null)
    }

    fun startAnotherReport() {
        _state.value = _state.value.copy(submittedReport = null, message = null, error = null)
    }

    override fun onCleared() {
        videoPublisher.let { publisher -> viewModelScope.launch { publisher.stop() } }
        super.onCleared()
    }

    private fun runRequest(block: suspend () -> Unit) {
        if (_state.value.loading) return
        _state.value = _state.value.copy(loading = true, error = null, message = null)
        viewModelScope.launch {
            try {
                block()
            } catch (error: Throwable) {
                _state.value = _state.value.copy(loading = false, error = repository.friendlyError(error))
            } finally {
                _state.value = _state.value.copy(loading = false)
            }
        }
    }
}
