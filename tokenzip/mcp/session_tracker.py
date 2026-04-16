"""Session-level token savings tracker.

Tracks cumulative savings across all compressions in a conversation
so the user can see real-time impact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CompressionEvent:
    """A single compression event."""

    timestamp: float
    files: list[str]
    original_tokens: int
    compressed_tokens: int
    original_chars: int
    compressed_chars: int

    @property
    def tokens_saved(self) -> int:
        return self.original_tokens - self.compressed_tokens

    @property
    def chars_saved(self) -> int:
        return self.original_chars - self.compressed_chars


class SessionTracker:
    """Tracks cumulative compression savings across a session."""

    def __init__(self):
        self.events: list[CompressionEvent] = []
        self.session_start = time.time()

    def record(
        self,
        files: list[str],
        original_tokens: int,
        compressed_tokens: int,
        original_chars: int,
        compressed_chars: int,
    ):
        self.events.append(CompressionEvent(
            timestamp=time.time(),
            files=files,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            original_chars=original_chars,
            compressed_chars=compressed_chars,
        ))

    @property
    def total_original_tokens(self) -> int:
        return sum(e.original_tokens for e in self.events)

    @property
    def total_compressed_tokens(self) -> int:
        return sum(e.compressed_tokens for e in self.events)

    @property
    def total_tokens_saved(self) -> int:
        return self.total_original_tokens - self.total_compressed_tokens

    @property
    def total_original_chars(self) -> int:
        return sum(e.original_chars for e in self.events)

    @property
    def total_compressed_chars(self) -> int:
        return sum(e.compressed_chars for e in self.events)

    @property
    def total_savings_pct(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (1 - self.total_compressed_tokens / self.total_original_tokens) * 100

    @property
    def num_compressions(self) -> int:
        return len(self.events)

    def summary(self) -> str:
        """Human-readable session summary."""
        lines = [
            "=== TokenZip Session Savings ===",
            f"Compressions: {self.num_compressions}",
            f"Original:     {self.total_original_tokens:,} tokens ({self.total_original_chars:,} chars)",
            f"Compressed:   {self.total_compressed_tokens:,} tokens ({self.total_compressed_chars:,} chars)",
            f"Saved:        {self.total_tokens_saved:,} tokens ({self.total_savings_pct:.1f}%)",
        ]

        if self.events:
            lines.append("")
            lines.append("Per-operation breakdown:")
            for i, event in enumerate(self.events, 1):
                files_str = ", ".join(event.files[:3])
                if len(event.files) > 3:
                    files_str += f" +{len(event.files) - 3} more"
                pct = (1 - event.compressed_tokens / event.original_tokens) * 100 if event.original_tokens else 0
                lines.append(
                    f"  #{i}: {files_str} | "
                    f"{event.original_tokens}→{event.compressed_tokens} tokens "
                    f"({pct:.0f}% saved)"
                )

        return "\n".join(lines)
