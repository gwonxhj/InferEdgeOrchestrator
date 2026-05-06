from __future__ import annotations

import argparse
from pathlib import Path


DETECTOR_ONNX = "detector_tiny.onnx"
CLASSIFIER_ONNX = "classifier_tiny.onnx"


def _require_onnx():
    try:
        import onnx
        from onnx import TensorProto, helper
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the dev extra before creating TensorRT diversity models."
        ) from exc
    return onnx, TensorProto, helper


def _float_tensor(helper, name: str, dims: list[int], values: list[float]):
    return helper.make_tensor(name, data_type=1, dims=dims, vals=values)


def build_detector_model():
    onnx, TensorProto, helper = _require_onnx()

    input_tensor = helper.make_tensor_value_info(
        "detector_input", TensorProto.FLOAT, [1, 3, 16, 16]
    )
    output_tensor = helper.make_tensor_value_info(
        "detector_scores", TensorProto.FLOAT, [1, 6]
    )

    conv_weights = [0.01 * ((idx % 9) + 1) for idx in range(4 * 3 * 3 * 3)]
    conv_bias = [0.0, 0.1, 0.2, 0.3]
    fc_weights = [0.001 * ((idx % 13) + 1) for idx in range(256 * 6)]
    fc_bias = [0.0 for _ in range(6)]

    nodes = [
        helper.make_node(
            "Conv",
            inputs=["detector_input", "detector_conv_w", "detector_conv_b"],
            outputs=["detector_conv"],
            kernel_shape=[3, 3],
            pads=[1, 1, 1, 1],
        ),
        helper.make_node("Relu", inputs=["detector_conv"], outputs=["detector_relu"]),
        helper.make_node(
            "AveragePool",
            inputs=["detector_relu"],
            outputs=["detector_pool"],
            kernel_shape=[2, 2],
            strides=[2, 2],
        ),
        helper.make_node("Flatten", inputs=["detector_pool"], outputs=["detector_flat"], axis=1),
        helper.make_node(
            "Gemm",
            inputs=["detector_flat", "detector_fc_w", "detector_fc_b"],
            outputs=["detector_scores"],
        ),
    ]
    initializers = [
        _float_tensor(helper, "detector_conv_w", [4, 3, 3, 3], conv_weights),
        _float_tensor(helper, "detector_conv_b", [4], conv_bias),
        _float_tensor(helper, "detector_fc_w", [256, 6], fc_weights),
        _float_tensor(helper, "detector_fc_b", [6], fc_bias),
    ]
    graph = helper.make_graph(
        nodes,
        "synthetic_detector_tiny",
        [input_tensor],
        [output_tensor],
        initializer=initializers,
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_operatorsetid("", 13)],
        ir_version=10,
        producer_name="inferedge_orchestrator",
    )
    onnx.checker.check_model(model)
    return model


def build_classifier_model():
    onnx, TensorProto, helper = _require_onnx()

    input_tensor = helper.make_tensor_value_info(
        "classifier_input", TensorProto.FLOAT, [1, 16]
    )
    output_tensor = helper.make_tensor_value_info(
        "classifier_logits", TensorProto.FLOAT, [1, 4]
    )

    hidden_weights = [0.01 * ((idx % 7) + 1) for idx in range(16 * 8)]
    hidden_bias = [0.05 for _ in range(8)]
    output_weights = [0.02 * ((idx % 5) + 1) for idx in range(8 * 4)]
    output_bias = [0.0 for _ in range(4)]

    nodes = [
        helper.make_node(
            "Gemm",
            inputs=["classifier_input", "classifier_hidden_w", "classifier_hidden_b"],
            outputs=["classifier_hidden"],
        ),
        helper.make_node(
            "Relu", inputs=["classifier_hidden"], outputs=["classifier_relu"]
        ),
        helper.make_node(
            "Gemm",
            inputs=["classifier_relu", "classifier_output_w", "classifier_output_b"],
            outputs=["classifier_logits"],
        ),
    ]
    initializers = [
        _float_tensor(helper, "classifier_hidden_w", [16, 8], hidden_weights),
        _float_tensor(helper, "classifier_hidden_b", [8], hidden_bias),
        _float_tensor(helper, "classifier_output_w", [8, 4], output_weights),
        _float_tensor(helper, "classifier_output_b", [4], output_bias),
    ]
    graph = helper.make_graph(
        nodes,
        "synthetic_classifier_tiny",
        [input_tensor],
        [output_tensor],
        initializer=initializers,
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_operatorsetid("", 13)],
        ir_version=10,
        producer_name="inferedge_orchestrator",
    )
    onnx.checker.check_model(model)
    return model


def write_models(output_dir: Path, model: str) -> list[Path]:
    onnx, _, _ = _require_onnx()
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[tuple[str, object]] = []
    if model in {"detector", "all"}:
        outputs.append((DETECTOR_ONNX, build_detector_model()))
    if model in {"classifier", "all"}:
        outputs.append((CLASSIFIER_ONNX, build_classifier_model()))

    written: list[Path] = []
    for filename, onnx_model in outputs:
        path = output_dir / filename
        onnx.save(onnx_model, path)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create synthetic ONNX models for TensorRT diversity smoke."
    )
    parser.add_argument(
        "--output-dir",
        default="models/generated",
        help="directory for generated ONNX files",
    )
    parser.add_argument(
        "--model",
        choices=("detector", "classifier", "all"),
        default="all",
        help="which synthetic model to create",
    )
    args = parser.parse_args()

    written = write_models(Path(args.output_dir), args.model)
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
