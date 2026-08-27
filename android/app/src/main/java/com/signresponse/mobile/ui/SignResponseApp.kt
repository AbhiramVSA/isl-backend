package com.signresponse.mobile.ui

import android.Manifest
import android.annotation.SuppressLint
import android.location.Location
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import io.livekit.android.renderer.SurfaceViewRenderer

private enum class Screen { Welcome, Login, Register, Dashboard, Emergency }

@Composable
fun SignResponseApp(viewModel: AppViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var screen by remember { mutableStateOf(if (state.signedIn) Screen.Dashboard else Screen.Welcome) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(state.message, state.error) {
        (state.message ?: state.error)?.let { snackbar.showSnackbar(it) }
        viewModel.clearMessages()
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Box(Modifier.padding(padding)) {
            when (screen) {
                Screen.Welcome -> WelcomeScreen(
                    onLogin = { screen = Screen.Login },
                    onRegister = { screen = Screen.Register },
                    loading = state.loading,
                    debugLoginAvailable = state.debugLoginAvailable,
                    onDebugLogin = { viewModel.debugLogin { screen = Screen.Dashboard } },
                )
                Screen.Login -> LoginScreen(
                    loading = state.loading,
                    onBack = { screen = Screen.Welcome },
                    onSubmit = { email, password ->
                        viewModel.login(email, password) { screen = Screen.Dashboard }
                    },
                )
                Screen.Register -> RegisterScreen(
                    loading = state.loading,
                    onBack = { screen = Screen.Welcome },
                    onSubmit = { name, email, phone, password ->
                        viewModel.register(name, email, phone, password) { screen = Screen.Dashboard }
                    },
                )
                Screen.Dashboard -> UserDashboard(
                    loading = state.loading,
                    profile = state.profile,
                    reports = state.reports,
                    onRefresh = viewModel::loadDashboard,
                    onEmergency = { viewModel.startAnotherReport(); screen = Screen.Emergency },
                    onSignOut = { viewModel.signOut { screen = Screen.Welcome } },
                )
                Screen.Emergency -> EmergencyScreen(
                    loading = state.loading,
                    submitted = state.submittedReport != null,
                    streaming = state.streaming,
                    recording = state.recording,
                    recordingAvailable = state.recordingAvailable,
                    transcribing = state.transcribing,
                    transcript = state.transcript,
                    onSend = viewModel::sendEmergency,
                    onEndVideo = viewModel::endVideo,
                    onTranscribe = viewModel::transcribeVideo,
                    onAttachPreview = viewModel::attachPreview,
                    onDetachPreview = viewModel::detachPreview,
                    onStartAnother = viewModel::startAnotherReport,
                    onSignOut = { viewModel.signOut { screen = Screen.Welcome } },
                    onDashboard = { viewModel.loadDashboard(); screen = Screen.Dashboard },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun UserDashboard(
    loading: Boolean,
    profile: com.signresponse.mobile.data.Identity?,
    reports: List<com.signresponse.mobile.data.Report>,
    onRefresh: () -> Unit,
    onEmergency: () -> Unit,
    onSignOut: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    Scaffold(
        topBar = { TopAppBar(title = { Text("My Dashboard", fontWeight = FontWeight.Bold) }, actions = { TextButton(onClick = onSignOut) { Text("Sign out") } }) },
    ) { padding ->
        Column(Modifier.padding(padding).padding(20.dp).fillMaxSize().verticalScroll(rememberScrollState())) {
            Text("Hello${profile?.name?.let { ", $it" } ?: ""}", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(profile?.email.orEmpty(), color = MaterialTheme.colorScheme.onSurfaceVariant)
            profile?.phone?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Spacer(Modifier.height(20.dp))
            Button(
                onClick = onEmergency,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.fillMaxWidth().height(68.dp),
            ) { androidx.compose.material3.Icon(Icons.Default.Videocam, null); Spacer(Modifier.size(8.dp)); Text("NEW EMERGENCY", fontWeight = FontWeight.ExtraBold) }
            Spacer(Modifier.height(26.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("My Reports", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                TextButton(onClick = onRefresh, enabled = !loading) { Text(if (loading) "Refreshing…" else "Refresh") }
            }
            if (reports.isEmpty() && !loading) Text("You have not submitted any reports yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            reports.forEach { report ->
                Spacer(Modifier.height(10.dp))
                Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(16.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(report.category, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Text(report.status.replace('_', ' '), color = if (report.status == "RESOLVED") Color(0xFF267359) else MaterialTheme.colorScheme.error, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(report.description, maxLines = 2, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    Text("Office: ${report.office.name}", fontSize = 13.sp)
                    report.assigned_officer?.let { Text("Officer: ${it.name}", fontSize = 13.sp) }
                }
            }
        }
    }
}

@Composable
private fun WelcomeScreen(
    onLogin: () -> Unit,
    onRegister: () -> Unit,
    loading: Boolean,
    debugLoginAvailable: Boolean,
    onDebugLogin: () -> Unit,
) {

    Column(
        Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(86.dp).background(MaterialTheme.colorScheme.primary, CircleShape),
            contentAlignment = Alignment.Center,
        ) { Text("+", color = Color.White, fontSize = 54.sp, fontWeight = FontWeight.Bold) }
        Spacer(Modifier.height(22.dp))
        Text("Sign Response", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            "Emergency help for deaf and hard-of-hearing people. Send your location and communicate with responding officers through sign-language video.",
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(36.dp))
        Button(onClick = onLogin, modifier = Modifier.fillMaxWidth().height(54.dp)) { Text("Login") }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onRegister, modifier = Modifier.fillMaxWidth().height(54.dp)) { Text("Create Account") }
        if (debugLoginAvailable) {
            Spacer(Modifier.height(24.dp))
            Text("Debug build", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            TextButton(onClick = onDebugLogin, enabled = !loading) { Text("Auto-login with saved account") }
        }

    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AuthScaffold(title: String, onBack: () -> Unit, content: @Composable (PaddingValues) -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, fontWeight = FontWeight.Bold) },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        content = content,
    )
}

@Composable
private fun LoginScreen(loading: Boolean, onBack: () -> Unit, onSubmit: (String, String) -> Unit) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    AuthScaffold("Login", onBack) { padding ->
        Column(Modifier.padding(padding).padding(24.dp).fillMaxSize(), verticalArrangement = Arrangement.Center) {
            Text("Welcome back", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("Sign in before sending an emergency request.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(24.dp))
            OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(password, { password = it }, label = { Text("Password") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(22.dp))
            Button(onClick = { onSubmit(email, password) }, enabled = email.isNotBlank() && password.isNotBlank() && !loading, modifier = Modifier.fillMaxWidth().height(54.dp)) {
                if (loading) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp) else Text("Login")
            }
        }
    }
}

@Composable
private fun RegisterScreen(loading: Boolean, onBack: () -> Unit, onSubmit: (String, String, String, String) -> Unit) {
    var name by remember { mutableStateOf("") }; var email by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }; var password by remember { mutableStateOf("") }
    AuthScaffold("Create Account", onBack) { padding ->
        Column(Modifier.padding(padding).padding(24.dp).fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.Center) {
            Text("Your details", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("This information helps officers respond safely.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(20.dp))
            OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(10.dp)); OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(10.dp)); OutlinedTextField(phone, { phone = it }, label = { Text("Phone (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(10.dp)); OutlinedTextField(password, { password = it }, label = { Text("Password — at least 10 characters") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(20.dp))
            Button(onClick = { onSubmit(name, email, phone, password) }, enabled = name.isNotBlank() && email.isNotBlank() && password.length >= 10 && !loading, modifier = Modifier.fillMaxWidth().height(54.dp)) {
                if (loading) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp) else Text("Create Account")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("MissingPermission")
@Composable
private fun EmergencyScreen(
    loading: Boolean,
    submitted: Boolean,
    streaming: Boolean,
    recording: Boolean,
    recordingAvailable: Boolean,
    transcribing: Boolean,
    transcript: String?,
    onSend: (String, String, Double, Double, Float?) -> Unit,
    onEndVideo: () -> Unit,
    onTranscribe: () -> Unit,
    onAttachPreview: (SurfaceViewRenderer) -> Unit,
    onDetachPreview: (SurfaceViewRenderer) -> Unit,
    onStartAnother: () -> Unit,
    onSignOut: () -> Unit,
    onDashboard: () -> Unit,
) {
    val context = LocalContext.current
    val locationClient = remember { LocationServices.getFusedLocationProviderClient(context) }
    var title by remember { mutableStateOf("") }; var description by remember { mutableStateOf("") }
    var location by remember { mutableStateOf<Location?>(null) }
    var locationError by remember { mutableStateOf<String?>(null) }
    fun loadCurrentLocation(onReady: (Location) -> Unit = {}) {
        locationError = null
        locationClient.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, null)
            .addOnSuccessListener { found ->
                location = found
                if (found == null) {
                    locationError = "Location is not ready. Turn on location and try again."
                } else {
                    onReady(found)
                }
            }
            .addOnFailureListener {
                locationError = "Location could not be read. Turn on location and try again."
            }
    }
    val locationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result.values.any { it }) {
            loadCurrentLocation()
        } else locationError = "Location permission is required to send help to the correct office."
    }
    fun requestLocation() = locationPermission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    val emergencyPermissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        val locationGranted = result[Manifest.permission.ACCESS_FINE_LOCATION] == true || result[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        val cameraGranted = result[Manifest.permission.CAMERA] == true
        val microphoneGranted = result[Manifest.permission.RECORD_AUDIO] == true
        if (!locationGranted || !cameraGranted || !microphoneGranted) {
            locationError = "Location, camera, and microphone permissions are required for the emergency video."
        } else {
            loadCurrentLocation { found ->
                onSend(title, description, found.latitude, found.longitude, found.accuracy)
            }
        }
    }
    fun sendAndStartCamera() = emergencyPermissions.launch(
        arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
        )
    )

    Scaffold(
        topBar = { TopAppBar(title = { Text("Emergency Help", fontWeight = FontWeight.Bold) }, navigationIcon = { TextButton(onClick = onDashboard, enabled = !streaming) { Text("Dashboard") } }, actions = { TextButton(onClick = onSignOut) { Text("Sign out") } }) },
    ) { padding ->
        Column(Modifier.padding(padding).padding(20.dp).fillMaxSize().verticalScroll(rememberScrollState()), horizontalAlignment = Alignment.CenterHorizontally) {
            if (submitted) {
                androidx.compose.material3.Icon(
                    if (streaming) Icons.Default.Videocam else Icons.Default.CheckCircle,
                    null,
                    tint = if (streaming) MaterialTheme.colorScheme.error else Color(0xFF267359),
                    modifier = Modifier.size(62.dp),
                )
                Text(if (streaming) "Camera is live" else "Help has been notified", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(
                    if (streaming && recording) "Officers can watch your signing now. This emergency video is being saved securely."
                    else if (streaming) "Officers can watch your signing now. Keep this app open."
                    else "Your report is still open and visible to the responsible office.",
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (streaming) {
                    Spacer(Modifier.height(18.dp))
                    CameraPreview(
                        onAttach = onAttachPreview,
                        onDetach = onDetachPreview,
                        modifier = Modifier.fillMaxWidth().height(360.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("Your camera preview", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
                }
                Spacer(Modifier.height(24.dp))
                if (streaming) Button(
                    onClick = onEndVideo,
                    enabled = !loading,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    modifier = Modifier.fillMaxWidth().height(64.dp),
                ) { Text(if (loading) "Ending…" else "END VIDEO", fontWeight = FontWeight.ExtraBold) }
                else {
                    if (recordingAvailable && transcript == null) {
                        Button(
                            onClick = onTranscribe,
                            enabled = !loading,
                            modifier = Modifier.fillMaxWidth().height(58.dp),
                        ) {
                            if (transcribing) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
                            else Text("START TRANSCRIPTION", fontWeight = FontWeight.ExtraBold)
                        }
                        Spacer(Modifier.height(14.dp))
                    }
                    transcript?.let {
                        Column(
                            Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(16.dp),
                        ) {
                            Text("Rough transcript", fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(6.dp))
                            Text(it, style = MaterialTheme.typography.titleMedium)
                        }
                        Spacer(Modifier.height(14.dp))
                    }
                    OutlinedButton(onClick = onStartAnother, enabled = !loading, modifier = Modifier.fillMaxWidth()) { Text("Send Another Report") }
                }
            } else {
                Text("Need urgent help?", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("Tap once to notify the correct office and start your sign-language video. Title and details are optional.", textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(22.dp))
                OutlinedTextField(title, { title = it }, label = { Text("What happened? (optional)") }, placeholder = { Text("For example: Accident or safety concern") }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(description, { description = it }, label = { Text("More details (optional)") }, minLines = 3, maxLines = 6, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(18.dp))
                OutlinedButton(onClick = ::requestLocation, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    androidx.compose.material3.Icon(Icons.Default.LocationOn, null); Spacer(Modifier.size(8.dp)); Text(if (location == null) "Prepare My Location" else "Location Ready")
                }
                locationError?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 8.dp), textAlign = TextAlign.Center) }
                Spacer(Modifier.height(22.dp))
                Button(
                    onClick = ::sendAndStartCamera,
                    enabled = !loading,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    shape = RoundedCornerShape(16.dp),
                    modifier = Modifier.fillMaxWidth().height(76.dp),
                ) {
                    androidx.compose.material3.Icon(Icons.Default.Videocam, null, Modifier.size(28.dp)); Spacer(Modifier.size(10.dp))
                    Text(if (loading) "STARTING…" else "EMERGENCY — START VIDEO", fontWeight = FontWeight.ExtraBold, fontSize = 17.sp)
                }
                Spacer(Modifier.height(12.dp))
                Text("Your camera and microphone start immediately after permissions are approved.", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp, textAlign = TextAlign.Center)
            }
        }
    }
}

@Composable
private fun CameraPreview(
    onAttach: (SurfaceViewRenderer) -> Unit,
    onDetach: (SurfaceViewRenderer) -> Unit,
    modifier: Modifier = Modifier,
) {
    var renderer by remember { mutableStateOf<SurfaceViewRenderer?>(null) }
    AndroidView(
        factory = { context ->
            SurfaceViewRenderer(context).also {
                renderer = it
                onAttach(it)
            }
        },
        modifier = modifier,
    )
    DisposableEffect(Unit) {
        onDispose {
            renderer?.let {
                onDetach(it)
                it.release()
            }
        }
    }
}
