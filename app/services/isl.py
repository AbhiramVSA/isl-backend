"""Word-level ISL recognition ported from
https://github.com/Sooryak12/Indian-Sign-Language-Recognition
(app.py + helper_functions.py).

Pipeline: video -> 45 evenly sampled frames -> MediaPipe Holistic
keypoints (pose + both hands, 258 features per frame) -> stacked LSTM
-> predicted word.
"""

import os
import tempfile

import cv2
import mediapipe as mp
import numpy as np
import skvideo.io

ACTIONS = ["Hello", "How are you", "thank you"]
SEQUENCE_LENGTH = 45
N_FEATURES = 258  # 33*4 pose + 21*3 left hand + 21*3 right hand landmarks

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov"}


def _build_model():
    from tensorflow.keras.layers import LSTM, Dense
    from tensorflow.keras.models import Sequential

    model = Sequential()
    model.add(
        LSTM(64, return_sequences=True, activation="relu",
             input_shape=(SEQUENCE_LENGTH, N_FEATURES))
    )
    model.add(LSTM(128, return_sequences=True, activation="relu"))
    model.add(LSTM(256, return_sequences=True, activation="relu"))
    model.add(LSTM(64, return_sequences=False, activation="relu"))
    model.add(Dense(64, activation="relu"))
    model.add(Dense(32, activation="relu"))
    model.add(Dense(len(ACTIONS), activation="softmax"))
    return model


class ISLRecognizer:
    def __init__(self, weights_path: str):
        if not os.path.exists(weights_path):
            raise FileNotFoundError(f"LSTM weights not found at {weights_path}")
        self.model = _build_model()
        self.model.load_weights(weights_path)

    def predict(self, video_bytes: bytes, suffix: str) -> str:
        # MediaPipe/skvideo read from disk, so spill the upload to a temp file.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(video_bytes)
            path = tmp.name
        try:
            sequence = self._video_to_keypoint_sequence(path)
        finally:
            os.remove(path)
        probabilities = self.model.predict(np.expand_dims(sequence, axis=0), verbose=0)
        return ACTIONS[int(np.argmax(probabilities))]

    def _video_to_keypoint_sequence(self, path: str) -> np.ndarray:
        try:
            frames = skvideo.io.vread(path)
        except Exception as exc:
            raise ValueError(f"Could not decode video: {exc}")
        n_frames = len(frames)
        if n_frames == 0:
            raise ValueError("Video contains no frames.")

        sequence = []
        holistic_cls = mp.solutions.holistic.Holistic
        with holistic_cls(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:
            if n_frames >= SEQUENCE_LENGTH:
                # Evenly sample SEQUENCE_LENGTH frames across the whole video.
                for i in range(SEQUENCE_LENGTH):
                    frame = frames[round(n_frames / SEQUENCE_LENGTH * i)]
                    sequence.append(self._extract_keypoints(frame, holistic))
            else:
                for frame in frames:
                    sequence.append(self._extract_keypoints(frame, holistic))
                # Zero-pad short videos to keep the input shape fixed.
                sequence.extend(
                    np.zeros(N_FEATURES) for _ in range(SEQUENCE_LENGTH - n_frames)
                )
        return np.array(sequence)

    @staticmethod
    def _extract_keypoints(frame: np.ndarray, holistic) -> np.ndarray:
        # Upstream reads frames with skvideo (RGB) and still applies BGR2RGB
        # before MediaPipe; the swap is kept so inference matches training.
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = holistic.process(image)

        pose = (
            np.array(
                [[lm.x, lm.y, lm.z, lm.visibility] for lm in results.pose_landmarks.landmark]
            ).flatten()
            if results.pose_landmarks
            else np.zeros(33 * 4)
        )
        lh = (
            np.array(
                [[lm.x, lm.y, lm.z] for lm in results.left_hand_landmarks.landmark]
            ).flatten()
            if results.left_hand_landmarks
            else np.zeros(21 * 3)
        )
        rh = (
            np.array(
                [[lm.x, lm.y, lm.z] for lm in results.right_hand_landmarks.landmark]
            ).flatten()
            if results.right_hand_landmarks
            else np.zeros(21 * 3)
        )
        return np.concatenate([pose, lh, rh])
