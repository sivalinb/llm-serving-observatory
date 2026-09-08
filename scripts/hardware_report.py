"""Print reproducible analytical portfolio examples; does not allocate model memory."""

import json

from observatory.hardware import HardwareRequest, estimate_with_sweep


def build_report():
    scenarios = {
        "baseline": {},
        "long_context": {"input_tokens": 32768},
        "four_bit_weights": {"weight_bits": 4},
        "half_memory_bandwidth": {"memory_gb_s": 500},
    }
    return {
        "schema_version": "1.0",
        "kind": "analytical_hardware_examples",
        "warning": "Hypothetical single-device estimates. Not GPU benchmark results.",
        "scenarios": {
            name: estimate_with_sweep(HardwareRequest(**inputs))
            for name, inputs in scenarios.items()
        },
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), indent=2, allow_nan=False))
