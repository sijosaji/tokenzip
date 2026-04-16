from dataclasses import dataclass, field


@dataclass
class TokenZipConfig:
    """Configuration for the TokenZip compression pipeline."""

    # Comment stripper
    keep_license_headers: bool = True
    keep_todo_comments: bool = True
    license_markers: list[str] = field(
        default_factory=lambda: ["license", "copyright", "spdx"]
    )

    # Dictionary coder
    min_pattern_length: int = 30
    min_pattern_frequency: int = 3
    max_dictionary_size: int = 50

    # RLE
    min_run_length: int = 4

    # Deduplicator
    min_block_size: int = 3  # minimum consecutive lines to consider a block
    similarity_threshold: float = 0.8  # for delta encoding

    # Safety
    max_compression_ratio: float = 0.50  # never compress more than 50%
    target_files: list[str] = field(default_factory=list)  # files to skip (user is editing these)

    # Output
    include_codebook: bool = True
    include_stats: bool = True
