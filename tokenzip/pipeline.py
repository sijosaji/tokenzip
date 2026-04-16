"""Main compression pipeline — chains all compressors with safety guardrails."""

import os
from pathlib import Path

from tokenzip.config import TokenZipConfig
from tokenzip.stats import CompressionStats, count_tokens
from tokenzip.compressors.comment_stripper import CommentStripper
from tokenzip.compressors.whitespace_normalizer import WhitespaceNormalizer
from tokenzip.compressors.rle_compressor import RLECompressor
from tokenzip.compressors.dictionary_coder import DictionaryCoder
from tokenzip.compressors.deduplicator import Deduplicator

# File extensions we know how to compress
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cc", ".go", ".rb", ".sh", ".bash", ".zsh", ".rs", ".swift", ".kt",
    ".kts", ".cs", ".php", ".css", ".scss", ".html", ".htm", ".xml",
    ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".sql", ".graphql",
    ".proto", ".dockerfile", ".tf", ".hcl",
}

# Files to always skip
SKIP_FILES = {
    ".env", ".env.local", ".env.production", "credentials.json",
    "secrets.yaml", "id_rsa", "id_ed25519",
}

# Max file size to process (1MB)
MAX_FILE_SIZE = 1_000_000


class CompressionPipeline:
    """Chains compressors together with stats tracking and safety guardrails."""

    def __init__(self, config: TokenZipConfig | None = None):
        self.config = config or TokenZipConfig()
        self.stats = CompressionStats()

        # Initialize compressors in order
        self.comment_stripper = CommentStripper(self.config)
        self.whitespace_normalizer = WhitespaceNormalizer(self.config)
        self.rle_compressor = RLECompressor(self.config)
        self.dictionary_coder = DictionaryCoder(self.config)
        self.deduplicator = Deduplicator(self.config)

    def compress_text(self, content: str, filename: str = "") -> str:
        """Compress a single text string."""
        result = self.compress_files({filename: content})
        return result.get(filename, content)

    def compress_files(self, files: dict[str, str]) -> dict[str, str]:
        """Compress multiple files through the full pipeline.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Mapping of filename -> compressed content, with codebook prepended.
        """
        # Filter out target files (files user is editing)
        target_files = set(self.config.target_files)
        to_compress = {
            fn: content
            for fn, content in files.items()
            if fn not in target_files
        }
        skipped = {
            fn: content
            for fn, content in files.items()
            if fn in target_files
        }

        # Track original size
        original_text = "\n".join(to_compress.values())
        self.stats.original_chars = len(original_text)
        self.stats.original_tokens = count_tokens(original_text)

        # Stage 1: Comment stripping (per-file)
        result = self._run_per_file_stage(
            "comment_stripper", self.comment_stripper, to_compress
        )

        # Stage 2: Whitespace normalization (per-file)
        result = self._run_per_file_stage(
            "whitespace_normalizer", self.whitespace_normalizer, result
        )

        # Stage 3: RLE compression (per-file)
        result = self._run_per_file_stage(
            "rle_compressor", self.rle_compressor, result
        )

        # Stage 4: Dictionary coding (cross-file)
        result = self._run_multi_file_stage(
            "dictionary_coder", self.dictionary_coder, result
        )

        # Stage 5: Cross-file deduplication (cross-file)
        result = self._run_multi_file_stage(
            "deduplicator", self.deduplicator, result
        )

        # Safety check: don't over-compress any single file
        for fn in result:
            if fn in files:
                original_len = len(files[fn])
                compressed_len = len(result[fn])
                if original_len > 0:
                    ratio = compressed_len / original_len
                    if ratio < (1 - self.config.max_compression_ratio):
                        # Over-compressed — back off to just comment + whitespace stripped
                        result[fn] = self.whitespace_normalizer.compress(
                            self.comment_stripper.compress(files[fn], fn), fn
                        )

        # Track final size
        compressed_text = "\n".join(result.values())
        self.stats.compressed_chars = len(compressed_text)
        self.stats.compressed_tokens = count_tokens(compressed_text)

        # Add codebook header if dictionary coder was used and it saves net chars
        if self.config.include_codebook and self.dictionary_coder.codebook:
            codebook_header = self.dictionary_coder.format_codebook_header()
            dict_savings = self.stats.stage_savings.get("dictionary_coder", 0)
            # Only include codebook if it saves more than its own overhead
            if dict_savings > len(codebook_header):
                first_file = next(iter(result))
                result[first_file] = codebook_header + result[first_file]

        # Merge back skipped files
        result.update(skipped)

        return result

    def _run_per_file_stage(
        self,
        stage_name: str,
        compressor,
        files: dict[str, str],
    ) -> dict[str, str]:
        """Run a per-file compressor and track stats."""
        before_chars = sum(len(c) for c in files.values())

        result = {
            fn: compressor.compress(content, fn)
            for fn, content in files.items()
        }

        after_chars = sum(len(c) for c in result.values())
        self.stats.record_stage(stage_name, before_chars, after_chars)

        return result

    def _run_multi_file_stage(
        self,
        stage_name: str,
        compressor,
        files: dict[str, str],
    ) -> dict[str, str]:
        """Run a multi-file compressor and track stats."""
        before_chars = sum(len(c) for c in files.values())

        result = compressor.compress_multi(files)

        after_chars = sum(len(c) for c in result.values())
        self.stats.record_stage(stage_name, before_chars, after_chars)

        return result


def load_files(path: str, target_files: list[str] | None = None) -> dict[str, str]:
    """Load files from a file path or directory.

    Args:
        path: Path to a file or directory.
        target_files: List of files to skip (user is editing these).

    Returns:
        Mapping of relative filename -> content.
    """
    target_set = set(target_files or [])
    files: dict[str, str] = {}
    p = Path(path)

    if p.is_file():
        if _should_include(p):
            files[p.name] = p.read_text(errors="replace")
    elif p.is_dir():
        for fp in sorted(p.rglob("*")):
            if not fp.is_file():
                continue
            if not _should_include(fp):
                continue
            if fp.stat().st_size > MAX_FILE_SIZE:
                continue

            rel = str(fp.relative_to(p))

            # Skip hidden directories
            if any(part.startswith(".") for part in fp.parts):
                continue

            # Skip common non-source directories
            if any(
                part in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build")
                for part in fp.parts
            ):
                continue

            if rel in target_set:
                continue

            try:
                files[rel] = fp.read_text(errors="replace")
            except (PermissionError, OSError):
                continue

    return files


def _should_include(path: Path) -> bool:
    """Check if a file should be included based on extension and name."""
    if path.name in SKIP_FILES:
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS
