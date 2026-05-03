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
