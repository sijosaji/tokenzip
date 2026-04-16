from dataclasses import dataclass, field


@dataclass
class CompressionStats:
    """Tracks compression statistics through the pipeline."""

    original_chars: int = 0
    compressed_chars: int = 0
    original_tokens: int | None = None
    compressed_tokens: int | None = None
    stage_savings: dict[str, int] = field(default_factory=dict)

    @property
    def char_savings_pct(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return (1 - self.compressed_chars / self.original_chars) * 100

    @property
    def token_savings_pct(self) -> float | None:
        if self.original_tokens is None or self.compressed_tokens is None:
            return None
        if self.original_tokens == 0:
            return 0.0
        return (1 - self.compressed_tokens / self.original_tokens) * 100

    def record_stage(self, stage_name: str, before_chars: int, after_chars: int):
        self.stage_savings[stage_name] = before_chars - after_chars

    def summary(self) -> str:
        lines = ["=== TokenZip Compression Report ==="]
        lines.append(f"Original:   {self.original_chars:,} chars")
        lines.append(f"Compressed: {self.compressed_chars:,} chars")
        lines.append(f"Savings:    {self.char_savings_pct:.1f}%")

        if self.original_tokens is not None:
            lines.append(f"Original:   {self.original_tokens:,} tokens")
            lines.append(f"Compressed: {self.compressed_tokens:,} tokens")
            lines.append(f"Token savings: {self.token_savings_pct:.1f}%")

        if self.stage_savings:
            lines.append("\nPer-stage savings (chars):")
            for stage, saved in self.stage_savings.items():
                lines.append(f"  {stage}: {saved:,}")

        return "\n".join(lines)


def count_tokens(text: str) -> int | None:
    """Count tokens using tiktoken if available."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return None
