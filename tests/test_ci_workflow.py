from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_workflow_keeps_package_cli_smoke() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "python -m pip install -e '.[dev]'" in workflow
    assert (
        "PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider"
        in workflow
    )
    assert "Run package CLI smoke" in workflow
    assert (
        "python -m inferedge_orchestrator run --config configs/phase1_demo.json "
        "--output reports/ci_phase1_demo.json --frames 3"
    ) in workflow
    assert (
        "python -m inferedge_orchestrator report --input "
        "reports/ci_phase1_demo.json"
    ) in workflow
    assert (
        "python -m inferedge_orchestrator compare-overload --config "
        "configs/phase3_overload.json --output reports/ci_phase3_overload.json "
        "--frames 5"
    ) in workflow
    assert "test -s reports/ci_phase1_demo.json" in workflow
    assert "test -s reports/ci_phase3_overload.json" in workflow


def test_ci_workflow_keeps_device_specific_paths_out_of_default_smoke() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    package_smoke = workflow.split("Run package CLI smoke", maxsplit=1)[1]

    assert "CAPTURE_TEGRASTATS" not in package_smoke
    assert "smoke_jetson" not in package_smoke
    assert "trtexec" not in package_smoke
    assert "ENGINE_PATH" not in package_smoke
    assert "onnxruntime" not in package_smoke
