package com.signresponse.mobile.data

import android.content.Context
import android.net.Uri
import com.signresponse.mobile.BuildConfig
import io.livekit.android.LiveKit
import io.livekit.android.renderer.SurfaceViewRenderer
import io.livekit.android.room.Room
import io.livekit.android.room.track.LocalVideoTrack

class LiveVideoPublisher(private val context: Context) {
    private var room: Room? = null
    private var videoTrack: LocalVideoTrack? = null
    private var preview: SurfaceViewRenderer? = null

    suspend fun start(serverUrl: String, accessToken: String) {
        stop()
        val videoRoom = LiveKit.create(context.applicationContext)
        val localVideoTrack = videoRoom.localParticipant.createVideoTrack()
        videoTrack = localVideoTrack
        room = videoRoom
        attachCurrentPreview()
        localVideoTrack.start()
        val apiHost = Uri.parse(BuildConfig.API_BASE_URL).host ?: "10.0.2.2"
        val deviceUrl = serverUrl
            .replace("ws://localhost", "ws://$apiHost")
            .replace("ws://127.0.0.1", "ws://$apiHost")
        videoRoom.connect(deviceUrl, accessToken)
        videoRoom.localParticipant.publishVideoTrack(localVideoTrack)
        videoRoom.localParticipant.setMicrophoneEnabled(true)
    }

    fun attachPreview(renderer: SurfaceViewRenderer) {
        if (preview === renderer) return
        preview?.let { old -> videoTrack?.removeRenderer(old) }
        preview = renderer
        attachCurrentPreview()
    }

    fun detachPreview(renderer: SurfaceViewRenderer) {
        if (preview !== renderer) return
        videoTrack?.removeRenderer(renderer)
        preview = null
    }

    private fun attachCurrentPreview() {
        val activeRoom = room ?: return
        val activeTrack = videoTrack ?: return
        val renderer = preview ?: return
        activeRoom.initVideoRenderer(renderer)
        renderer.setMirror(true)
        activeTrack.addRenderer(renderer)
    }

    suspend fun stop() {
        room?.let { activeRoom ->
            preview?.let { renderer -> videoTrack?.removeRenderer(renderer) }
            runCatching { videoTrack?.stop() }
            runCatching { activeRoom.localParticipant.setMicrophoneEnabled(false) }
            activeRoom.disconnect()
            activeRoom.release()
        }
        videoTrack = null
        room = null
    }
}
