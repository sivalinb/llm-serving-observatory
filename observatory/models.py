from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["combined", "disaggregated", "upstream"] = "disaggregated"
    prompt: str = Field(default="Explain prefill, decode, and the KV cache.", max_length=32000)
    input_tokens: int = Field(default=512, ge=1, le=8192)
    output_tokens: int = Field(default=32, ge=1, le=256)
    reasoning_tokens: int = Field(default=0, ge=0, le=128)
    prefix_tokens: int = Field(default=256, ge=0, le=8192)
    prefix_key: str = Field(default="shared-system-prompt", max_length=100)
    cache_enabled: bool = True
    prefill_tps: float = Field(default=4000, ge=250, le=100000)
    decode_tps: float = Field(default=100, ge=10, le=1000)
    transfer_mb_s: float = Field(default=1000, ge=10, le=100000)
    transfer_latency_ms: float = Field(default=3, ge=0, le=500)
    fault: Literal["none", "transfer_failure"] = "none"
    ttft_slo_ms: float = Field(default=750, ge=1, le=60000)
    tpot_slo_ms: float = Field(default=50, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_counts(self):
        # Reasoning is a subset of output, and at least one visible token is required.
        if self.reasoning_tokens >= self.output_tokens:
            raise ValueError("reasoning_tokens must be less than output_tokens")
        self.prefix_tokens = min(self.prefix_tokens, self.input_tokens)
        return self


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: LabRequest = Field(default_factory=LabRequest)
    requests: int = Field(default=8, ge=1, le=64)
    concurrency: int = Field(default=2, ge=1, le=8)
    compare: bool = True
    warmup: int = Field(default=1, ge=0, le=3)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=32000)


class ChatRequest(BaseModel):
    """Deliberately narrow, documented OpenAI chat-completions subset."""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="simulator", max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(default=32, ge=1, le=256)
    stream: bool = False
    temperature: float = Field(default=0, ge=0, le=2)
    stream_options: dict | None = None
