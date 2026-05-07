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
    Path("examples/telemetry/phase3_overload_sample.json"),
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
