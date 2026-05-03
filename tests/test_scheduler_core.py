from __future__ import annotations

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.policy import LoadSheddingPolicy
from inferedge_orchestrator.scheduler import PriorityScheduler
from inferedge_orchestrator.task_queue import BoundedTaskQueues


def _task(name: str, priority: int, queue_size: int = 4) -> TaskConfig:
    return TaskConfig(
        name=name,
        model_path="",
        priority=priority,
        target_fps=10.0,
        latency_budget_ms=100.0,
        queue_size=queue_size,
        drop_policy="drop_oldest",
    )


def _frame(task_name: str, sequence: int, *, deadline: float = 100.0) -> FrameEnvelope:
    return FrameEnvelope(
        frame_id=f"{task_name}-{sequence}",
        task_name=task_name,
        sequence=sequence,
        created_at_ms=float(sequence),
        deadline_at_ms=deadline,
    )


def test_scheduler_prioritizes_high_priority_task() -> None:
    low = _task("classifier", priority=10)
    high = _task("detector", priority=100)
    queues = BoundedTaskQueues((low, high))
    queues.enqueue(_frame("classifier", 1))
    queues.enqueue(_frame("detector", 2))

    decision = PriorityScheduler((low, high)).choose_next(queues)

    assert decision is not None
    assert decision.task_name == "detector"


def test_scheduler_uses_deadline_within_same_priority() -> None:
    first = _task("ocr", priority=50)
    second = _task("classifier", priority=50)
    queues = BoundedTaskQueues((first, second))
    queues.enqueue(_frame("ocr", 1, deadline=200.0))
    queues.enqueue(_frame("classifier", 2, deadline=120.0))

    decision = PriorityScheduler((first, second)).choose_next(queues)

    assert decision is not None
    assert decision.task_name == "classifier"


def test_queue_overflow_drops_oldest_frame() -> None:
    task = _task("detector", priority=100, queue_size=1)
    queues = BoundedTaskQueues((task,))
    queues.enqueue(_frame("detector", 1))
    result = queues.enqueue(_frame("detector", 2))

    assert result.accepted is True
    assert result.dropped is not None
    assert result.dropped.frame_id == "detector-1"
    assert queues.pop("detector").frame_id == "detector-2"


def test_load_shedding_drops_low_priority_before_high_priority() -> None:
    high = _task("detector", priority=100, queue_size=4)
    low = _task("classifier", priority=10, queue_size=4)
    queues = BoundedTaskQueues((high, low))
    queues.enqueue(_frame("detector", 1))
    queues.enqueue(_frame("classifier", 2))
    queues.enqueue(_frame("classifier", 3))

    drops, decisions = LoadSheddingPolicy(
        (high, low),
        backlog_threshold=2,
    ).apply(queues)

    assert [drop.task_name for drop in drops] == ["classifier"]
    assert queues.backlog("detector") == 1
    assert queues.backlog("classifier") == 1
    assert decisions[0].protected_task == "detector"
    assert decisions[0].limited_task == "classifier"
