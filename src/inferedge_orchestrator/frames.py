from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig


@dataclass(frozen=True)
class FrameEnvelope:
    frame_id: str
    task_name: str
    sequence: int
    created_at_ms: float
    deadline_at_ms: float
    payload: object | None = None


class DummyFrameSource:
    """Generates deterministic frame envelopes for scheduler tests and demos."""

    def __init__(self) -> None:
        self._sequence = 0

    def frames_for_cycle(
        self,
        tasks: tuple[TaskConfig, ...],
        *,
        cycle: int,
        now_ms: float,
    ) -> list[FrameEnvelope]:
        frames: list[FrameEnvelope] = []
        for task in tasks:
            if cycle % task.emit_every_cycles != 0:
                continue
            self._sequence += 1
            frames.append(
                FrameEnvelope(
                    frame_id=f"{task.name}-{cycle}-{self._sequence}",
                    task_name=task.name,
                    sequence=self._sequence,
                    created_at_ms=now_ms,
                    deadline_at_ms=now_ms + task.latency_budget_ms,
                    payload={"source": "dummy", "cycle": cycle},
                )
            )
        return frames


class FileFrameSource:
    """Routes file-backed metadata to workers without binding scheduler logic."""

    def __init__(self, *, source: str, path: str) -> None:
        self._source = source
        self._path = str(Path(path))
        self._sequence_paths = (
            _image_sequence_paths(Path(path)) if source == "image_sequence" else ()
        )
        self._sequence = 0

    def frames_for_cycle(
        self,
        tasks: tuple[TaskConfig, ...],
        *,
        cycle: int,
        now_ms: float,
    ) -> list[FrameEnvelope]:
        frames: list[FrameEnvelope] = []
        for task in tasks:
            if cycle % task.emit_every_cycles != 0:
                continue
            self._sequence += 1
            selected_path = self._path
            if self._sequence_paths:
                selected_path = str(
                    self._sequence_paths[cycle % len(self._sequence_paths)]
                )
            payload = {
                "source": self._source,
                "path": selected_path,
                "frame_index": cycle,
            }
            if self._sequence_paths:
                payload["sequence_root"] = self._path
            frames.append(
                FrameEnvelope(
                    frame_id=f"{task.name}-{cycle}-{self._sequence}",
                    task_name=task.name,
                    sequence=self._sequence,
                    created_at_ms=now_ms,
                    deadline_at_ms=now_ms + task.latency_budget_ms,
                    payload=payload,
                )
            )
        return frames


def build_frame_source(config: OrchestratorConfig) -> DummyFrameSource | FileFrameSource:
    if config.input_source == "dummy":
        return DummyFrameSource()
    if config.input_path is None:
        raise ValueError(f"{config.input_source} input_source requires input_path")
    return FileFrameSource(source=config.input_source, path=config.input_path)


def _image_sequence_paths(path: Path) -> tuple[Path, ...]:
    if not path.exists():
        raise FileNotFoundError(f"image_sequence input path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"image_sequence input path must be a directory: {path}")
    extensions = {".jpg", ".jpeg", ".png", ".ppm", ".bmp"}
    images = tuple(
        sorted(
            child
            for child in path.iterdir()
            if child.is_file() and child.suffix.lower() in extensions
        )
    )
    if not images:
        raise ValueError(f"image_sequence input path has no supported image files: {path}")
    return images
