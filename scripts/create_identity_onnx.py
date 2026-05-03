from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="output .onnx path")
    args = parser.parse_args()

    try:
        import onnx
        from onnx import TensorProto, helper
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the dev extra before creating the smoke model.") from exc

    input_tensor = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 2])
    output_tensor = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2])
    node = helper.make_node("Identity", inputs=["input"], outputs=["output"])
    graph = helper.make_graph([node], "identity_graph", [input_tensor], [output_tensor])
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_operatorsetid("", 13)],
        ir_version=10,
    )
    onnx.checker.check_model(model)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, output)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
