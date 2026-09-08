"""Transparent, small in-repository retrieval fixture, not an independent model-quality eval."""

import json

from observatory.retrieval import CORPUS_VERSION, search

CASES = [
    ("How do TTFT prefill and decode relate?", "latency"),
    ("What is time to first token?", "latency"),
    ("Why does KV cache transfer add latency?", "cache"),
    ("What is disaggregated serving?", "cache"),
    ("Are reasoning tokens part of output tokens?", "tokens"),
    ("What are cached input and extended tokens?", "tokens"),
    ("How is HBM different from CPU RAM?", "memory"),
    ("Where do weights and activations fit in memory?", "memory"),
    ("How does quantization reduce model memory?", "memory"),
    ("How do Prometheus Grafana and traces work?", "telemetry"),
    ("How is RSS measured?", "telemetry"),
    ("How do I deploy in Phoenix Free Tier?", "phx"),
    ("How are access keys and invitations secured?", "security"),
    ("How do daily quotas protect capacity?", "security"),
    ("Can citations prove an answer is factual?", "citations"),
]


def evaluate():
    rows = [
        {
            "query": query,
            "expected": expected,
            "retrieved": [s["document_id"] for s in search(query)],
        }
        for query, expected in CASES
    ]
    return {
        "corpus_version": CORPUS_VERSION,
        "cases": len(rows),
        "recall_at_3": sum(row["expected"] in row["retrieved"] for row in rows) / len(rows),
        "scope": "in-repository teaching fixture; not held-out or answer-quality evaluation",
        "results": rows,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
