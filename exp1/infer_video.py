from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
from local_test import (
    SignRecorder,
    choose_device,
    ensure_holistic_model,
    load_classifier,
    predict,
    pretty_label,
)


def infer_video(
    video_path: Path,
    checkpoint_path: Path,
    holistic_model_path: Path,
    *,
    segment_seconds: float,
    topk: int,
    device_name: str,
) -> dict:
    device = choose_device(device_name)
    model, checkpoint, idx_to_label = load_classifier(checkpoint_path, device)
    holistic_model = ensure_holistic_model(holistic_model_path)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("The uploaded video could not be opened.")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not 1 <= fps <= 240:
        fps = 30.0
    frames_per_segment = max(1, round(fps * segment_seconds))
    recorder = SignRecorder(holistic_model, fps)
    words: list[dict] = []
    frame_number = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            recorder.add_frame(frame)
            frame_number += 1
            if recorder.frame_index < frames_per_segment:
                continue
            predictions, stats = predict(
                model,
                device,
                idx_to_label,
                checkpoint["preprocessing_config"],
                recorder.arrays(),
                topk,
            )
            if _has_signing_landmarks(stats):
                words.append(_word_result(predictions, stats, frame_number, fps, segment_seconds))
            recorder.reset()

        if recorder.frame_index >= max(8, round(fps * 0.4)):
            predictions, stats = predict(
                model,
                device,
                idx_to_label,
                checkpoint["preprocessing_config"],
                recorder.arrays(),
                topk,
            )
            if _has_signing_landmarks(stats):
                words.append(
                    _word_result(
                        predictions,
                        stats,
                        frame_number,
                        fps,
                        recorder.frame_index / fps,
                    )
                )
    finally:
        recorder.close()
        capture.release()

    if not words:
        raise RuntimeError("The uploaded video did not contain enough readable frames.")

    collapsed: list[dict] = []
    for word in words:
        if collapsed and collapsed[-1]["word"] == word["word"]:
            if word["confidence"] > collapsed[-1]["confidence"]:
                collapsed[-1] = word
            continue
        collapsed.append(word)

    return {
        "transcript": " ".join(item["word"] for item in collapsed),
        "words": collapsed,
        "model": "exp1 INCLUDE isolated-sign classifier",
    }


def _has_signing_landmarks(stats: dict) -> bool:
    return (
        stats["pose_rate"] >= 0.35
        and max(stats["left_rate"], stats["right_rate"]) >= 0.1
    )


def _word_result(predictions, stats, end_frame: int, fps: float, duration: float) -> dict:
    label, confidence = predictions[0]
    end_seconds = end_frame / fps
    return {
        "word": pretty_label(label),
        "confidence": confidence,
        "start_seconds": max(0.0, end_seconds - duration),
        "end_seconds": end_seconds,
        "alternatives": [
            {"word": pretty_label(candidate), "confidence": probability}
            for candidate, probability in predictions[1:]
        ],
        "landmarks": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run exp1 inference on a video file.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--holistic-model", type=Path, required=True)
    parser.add_argument("--segment-seconds", type=float, default=2.5)
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    result = infer_video(
        args.video,
        args.checkpoint,
        args.holistic_model,
        segment_seconds=args.segment_seconds,
        topk=args.topk,
        device_name=args.device,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
