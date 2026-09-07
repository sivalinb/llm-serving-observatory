# Validation record

Validation performed locally on 2026-09-07 with Python 3.12.14 on macOS ARM64.

- 20 pytest tests passed, covering token accounting, prefix eviction, cancellation, failure recovery, W3C context propagation, upstream stream parsing, usage unknowns, API authentication, config and SVG parsing.
- Ruff checks, JavaScript syntax, and shell syntax passed.
- Terraform 1.9.8 validated against oracle/oci 6.37.0; no cloud resources were created.
- Real HTTP smoke test passed with the gateway and two separate simulated worker processes.
- Browser: live streaming, ledger, waterfall, architecture, and comparison workflows checked. Benchmark page reported zero browser console errors.
- Docker Engine is not installed on the local host. Docker build/Compose execution is configured in GitHub Actions and is not included in the local test claim.
- No real GPU, real model weights, OCI credentials, ADB wallet, or OCI APM domain was supplied. The GPU recipe and cloud export paths require environment validation.

Two upstream test-library deprecation warnings were observed (Starlette/httpx and an AnyIO alias); tests passed.

## Recorded sample

The adjacent JSON is the actual local closed-loop simulation run: 8 requests per mode, concurrency 2, 1 warmup per mode. Warmups are excluded from reported samples. Input/output lengths: 128/32 synthetic units. This is not an OCI or GPU benchmark.

| Mode | p95 TTFT (ms) | p95 TPOT (ms) | Output tokens/s | Errors |
|---|---:|---:|---:|---:|
| combined | 432.64 | 11.82 | 84.47 | 0 |
| disaggregated | 408.14 | 11.86 | 85.58 | 0 |

Combined owns one slot; disaggregated owns separate prefill/decode slots. The small differences in this sample are descriptive only. More repetitions, controlled hardware and equal resource budgets are required for a performance conclusion.
