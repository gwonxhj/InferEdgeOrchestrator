from __future__ import annotations

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig
from inferedge_orchestrator.frames import build_frame_source


def test_image_source_routes_file_payload_to_task() -> None:
    config = OrchestratorConfig(
        tasks=(
            TaskConfig(
                name="detector",
                model_path="",
                priority=100,
                target_fps=5,
                latency_budget_ms=100,
                queue_size=2,
            ),
        ),
        input_source="image",
        input_path="samples/frame.jpg",
    )

    frames = build_frame_source(config).frames_for_cycle(
        config.tasks,
        cycle=7,
        now_ms=0.0,
    )

    assert frames[0].payload == {
        "source": "image",
        "path": "samples/frame.jpg",
        "frame_index": 7,
    }


def test_video_source_routes_frame_index_payload_to_task() -> None:
    config = OrchestratorConfig(
        tasks=(
            TaskConfig(
                name="detector",
                model_path="",
                priority=100,
                target_fps=5,
                latency_budget_ms=100,
                queue_size=2,
            ),
        ),
        input_source="video",
        input_path="samples/demo.mp4",
    )

    frames = build_frame_source(config).frames_for_cycle(
        config.tasks,
        cycle=3,
        now_ms=0.0,
    )

    assert frames[0].payload["source"] == "video"
    assert frames[0].payload["frame_index"] == 3


def test_image_sequence_source_rotates_file_payloads(tmp_path) -> None:
    (tmp_path / "frame_b.ppm").write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")
    (tmp_path / "frame_a.ppm").write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    config = OrchestratorConfig(
        tasks=(
            TaskConfig(
                name="detector",
                model_path="",
                priority=100,
                target_fps=5,
                latency_budget_ms=100,
                queue_size=2,
            ),
        ),
        input_source="image_sequence",
        input_path=str(tmp_path),
    )

    source = build_frame_source(config)
    first = source.frames_for_cycle(config.tasks, cycle=0, now_ms=0.0)[0]
    second = source.frames_for_cycle(config.tasks, cycle=1, now_ms=1.0)[0]
    third = source.frames_for_cycle(config.tasks, cycle=2, now_ms=2.0)[0]

    assert first.payload["source"] == "image_sequence"
    assert first.payload["path"].endswith("frame_a.ppm")
    assert first.payload["sequence_root"] == str(tmp_path)
    assert second.payload["path"].endswith("frame_b.ppm")
    assert third.payload["path"].endswith("frame_a.ppm")
