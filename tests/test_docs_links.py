from __future__ import annotations

import re
from pathlib import Path


DOC_ROOTS = (
    Path("."),
    Path("configs"),
    Path("docs"),
    Path("examples/telemetry"),
)
EXTERNAL_LINK_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
)
EXPECTED_SAMPLE_ARTIFACTS = {
    Path("examples/telemetry/agent_scheduler_delay_sample.json"),
    Path("examples/telemetry/phase3_overload_sample.json"),
    Path("examples/telemetry/remote_fallback_recovery_sample.json"),
    Path("examples/telemetry/jetson_smoke_dummy_sample.json"),
    Path("examples/telemetry/jetson_onnx_smoke_sample.json"),
    Path("examples/telemetry/jetson_tensorrt_contention_sample.json"),
    Path("examples/telemetry/jetson_tensorrt_diverse_contention_sample.json"),
}
REPO_ROOT = Path(".").resolve()

MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    files: set[Path] = set()
    for root in DOC_ROOTS:
        if root == Path("."):
            files.update(path for path in root.glob("*.md") if path.is_file())
        else:
            files.update(path for path in root.glob("*.md") if path.is_file())
    return sorted(files)


def _strip_fragment(target: str) -> str:
    return target.split("#", 1)[0]


def _is_external_or_anchor(target: str) -> bool:
    return (
        target.startswith(EXTERNAL_LINK_PREFIXES)
        or target.startswith("#")
        or not _strip_fragment(target)
    )


def _english_pair_for(path: Path) -> Path:
    if path.name.endswith(".ko.md"):
        return path.with_name(path.name.removesuffix(".ko.md") + ".md")
    return path


def _korean_pair_for(path: Path) -> Path:
    if path.name.endswith(".ko.md"):
        return path
    return path.with_name(path.name.removesuffix(".md") + ".ko.md")


def test_markdown_docs_have_language_selectors() -> None:
    for path in _markdown_files():
        first_lines = path.read_text(encoding="utf-8").splitlines()[:5]
        assert any(line.startswith("Language:") for line in first_lines), (
            f"missing language selector near top of {path}"
        )


def test_english_and_korean_doc_pairs_exist() -> None:
    for path in _markdown_files():
        assert _english_pair_for(path).exists(), f"missing English pair for {path}"
        assert _korean_pair_for(path).exists(), f"missing Korean pair for {path}"


def test_internal_markdown_links_resolve() -> None:
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            if _is_external_or_anchor(target):
                continue
            target = _strip_fragment(target)
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(REPO_ROOT)
            except ValueError as exc:
                raise AssertionError(
                    f"{path} links outside the repository: {target}"
                ) from exc
            assert resolved.exists(), f"{path} links to missing target: {target}"


def test_readmes_expose_orchestrator_role_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_ko = Path("README.ko.md").read_text(encoding="utf-8")

    assert "Language: English | [한국어](README.ko.md)" in readme
    assert "Language: [English](README.md) | 한국어" in readme_ko

    for required in [
        "## Role Boundary At A Glance",
        "Decide whether a model is deployable",
        "Own comparability, regression calculation, evidence registry",
        "Claim production remote execution",
        "Replace Triton, DeepStream, Kubernetes, or a production inference server",
    ]:
        assert required in readme

    for required in [
        "## 역할 경계 한눈에 보기",
        "모델이 deployable한지 결정하거나 Lab `deployment_decision`을 덮어쓰지 않음",
        "comparability, regression 계산, evidence registry, deployment decision을 소유하지 않음",
        "production remote execution",
        "Triton, DeepStream, Kubernetes, production inference server를 대체하지 않음",
    ]:
        assert required in readme_ko


def test_operation_control_guides_expose_runtime_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_ko = Path("README.ko.md").read_text(encoding="utf-8")
    guide = Path("docs/operation_control.md").read_text(encoding="utf-8")
    guide_ko = Path("docs/operation_control.ko.md").read_text(encoding="utf-8")

    assert "[docs/operation_control.md](docs/operation_control.md)" in readme
    assert "[한국어](docs/operation_control.ko.md)" in readme
    assert (
        "[docs/operation_control.ko.md](docs/operation_control.ko.md)"
        in readme_ko
    )
    assert "[English](docs/operation_control.md)" in readme_ko

    assert "Language: English | [한국어](operation_control.ko.md)" in guide
    assert "Language: [English](operation_control.md) | 한국어" in guide_ko

    for required in [
        "runtime operation control layer",
        "not a benchmark tool",
        "Queue control",
        "Overload handling",
        "Latency budget protection",
        "Fallback evidence",
        "`edgeenv_runtime_telemetry_feed`",
        "Lab remains the final deployment decision owner",
        "production remote execution",
        "cloud control plane",
        "Kubernetes-style orchestration",
        "Triton replacement",
        "Jetson device is required only when collecting new live device-local evidence",
    ]:
        assert required in guide

    for required in [
        "runtime operation control layer",
        "benchmark tool이 아니다",
        "Queue control",
        "Overload handling",
        "Latency budget protection",
        "Fallback evidence",
        "`edgeenv_runtime_telemetry_feed`",
        "Lab remains the final deployment decision owner",
        "production remote execution",
        "cloud control plane",
        "Kubernetes-style orchestration",
        "Triton replacement",
        "Jetson 필요 여부",
    ]:
        assert required in guide_ko


def test_sample_telemetry_artifacts_are_linked_from_evidence_docs() -> None:
    evidence_docs = (
        Path("docs/validation_evidence.md"),
        Path("docs/validation_evidence.ko.md"),
    )
    for artifact in EXPECTED_SAMPLE_ARTIFACTS:
        assert artifact.exists(), f"missing sample telemetry artifact: {artifact}"
        for doc in evidence_docs:
            relative = artifact.relative_to(Path(".")).as_posix()
            assert relative in doc.read_text(encoding="utf-8"), (
                f"{doc} does not link to {artifact}"
            )


def test_validation_evidence_docs_scope_ci_smoke_as_portable() -> None:
    evidence = Path("docs/validation_evidence.md").read_text(encoding="utf-8")
    evidence_ko = Path("docs/validation_evidence.ko.md").read_text(
        encoding="utf-8"
    )

    for text in (evidence, evidence_ko):
        assert "CI package/install smoke" in text
        assert "portable" in text
        assert "CLI entrypoint" in text
        assert "Jetson physical-device smoke evidence" in text
        assert "default CI smoke" in text
        assert "Jetson-only device access" in text
        assert "TensorRT engine execution" in text
        assert "ONNX Runtime optional-backend validation" in text
        assert "device SSH" in text


def test_telemetry_sample_readmes_offer_reviewer_quick_path() -> None:
    readme = Path("examples/telemetry/README.md").read_text(encoding="utf-8")
    readme_ko = Path("examples/telemetry/README.ko.md").read_text(
        encoding="utf-8"
    )

    for text in (readme, readme_ko):
        assert "## Reviewer Quick Path" in text
        assert "phase3_overload_sample.json" in text
        assert "agent_scheduler_delay_sample.json" in text
        assert "remote_fallback_recovery_sample.json" in text
        assert "jetson_*_sample.json" in text
        assert "high-priority" in text
        assert "scheduler-delay evidence" in text
        assert "bounded fallback recovery" in text
        assert "portable CI" in text
