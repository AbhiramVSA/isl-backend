"""Inference pipeline ported from
https://github.com/Karthikeyu/Indian-sign-language-recognition
(recogniseGesture.py + imagePreprocessingUtils.py).

Pipeline: skin mask + Canny edges -> SURF descriptors -> KMeans visual
words -> bag-of-visual-words histogram -> SVM classification.
"""

import pickle

import cv2
import numpy as np

# Upstream labels come from the sorted data/ directory names: digits 1-9, then A-Z.
CLASS_LABELS = [str(d) for d in range(1, 10)] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]

N_CLASSES = 35
CLUSTER_FACTOR = 8
IMG_SIZE = 128


class ISLRecognizer:
    def __init__(self, kmeans_path: str, svm_path: str):
        with open(kmeans_path, "rb") as f:
            self.kmeans = pickle.load(f)
        with open(svm_path, "rb") as f:
            self.svm = pickle.load(f)
        # SURF is patented: only available in OpenCV builds with non-free
        # algorithms enabled (see README). Fail fast if it isn't.
        self.surf = cv2.xfeatures2d.SURF_create()

    def predict(self, image_bytes: bytes) -> str:
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Could not decode image.")
        image = cv2.resize(image, (IMG_SIZE, IMG_SIZE))
        edges = self._canny_edges(image)
        descriptors = self._surf_descriptors(edges)
        if descriptors is None:
            raise ValueError("No SURF descriptors found in image (is a hand gesture visible?).")
        visual_words = self.kmeans.predict(descriptors)
        histogram = np.bincount(visual_words, minlength=N_CLASSES * CLUSTER_FACTOR)
        prediction = self.svm.predict([histogram])
        return CLASS_LABELS[prediction[0]]

    @staticmethod
    def _canny_edges(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        lower = np.array([0, 40, 30], dtype="uint8")
        upper = np.array([43, 255, 254], dtype="uint8")
        skin_mask = cv2.inRange(hsv, lower, upper)
        skin_mask = cv2.addWeighted(skin_mask, 0.5, skin_mask, 0.5, 0.0)
        skin_mask = cv2.medianBlur(skin_mask, 5)
        skin = cv2.bitwise_and(gray, gray, mask=skin_mask)
        return cv2.Canny(skin, 60, 60)

    def _surf_descriptors(self, edges: np.ndarray):
        edges = cv2.resize(edges, (256, 256))
        _, descriptors = self.surf.detectAndCompute(edges, None)
        return descriptors
