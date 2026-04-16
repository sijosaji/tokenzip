"""TokenZip MCP Server.

Provides compressed file reading for AI coding tools.
Works with Claude Code, Cline, Cursor, and any MCP-compatible client.

Tools:
  - read_compressed: Read one or more files with TokenZip compression
  - compress_context: Compress a directory of files for context loading
  - session_savings: Show cumulative token savings for this session

The codebook is always prepended so the model understands the compressed notation.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tokenzip.config import TokenZipConfig
from tokenzip.pipeline import CompressionPipeline, load_files, SUPPORTED_EXTENSIONS
from tokenzip.stats import count_tokens
from tokenzip.mcp.session_tracker import SessionTracker

# ── Server setup ─────────────────────────────────────────────────

mcp = FastMCP(
    "tokenzip",
    instructions="TokenZip — Compress code context to save LLM tokens. "
    "Reads files through a compression pipeline that strips comments, "
    "deduplicates patterns, and builds a codebook. Saves 20-30% tokens "
    "while preserving all code logic and structure.",
)

# Session-wide tracker
tracker = SessionTracker()

# Default config
DEFAULT_CONFIG = TokenZipConfig(
    min_pattern_length=20,
    min_pattern_frequency=2,
    keep_todo_comments=True,
    keep_license_headers=True,
)

CODEBOOK_INSTRUCTIONS = """[TOKENZIP COMPRESSED]
The content below has been compressed by TokenZip to save tokens.
- [D1], [D2], etc. are codebook references — see the CODEBOOK section for their full text.
- [same as file:lines] means that block is identical to the referenced location.
- [delta from file] means the file is expressed as differences from the reference file.
All variable names, function names, and logic are preserved exactly.
"""


# ── Tools ────────────────────────────────────────────────────────


@mcp.tool()
def read_compressed(
    paths: list[str],
    target_file: str = "",
) -> str:
    """Read one or more files with TokenZip compression applied.

    Use this instead of reading files directly when you need context from
    multiple files. Saves 20-30% tokens while preserving all code structure.

    Args:
        paths: List of file or directory paths to read and compress.
        target_file: The file you plan to edit (will be returned uncompressed
                     so you can see exact content). Optional.
    """
    all_files: dict[str, str] = {}

    for path in paths:
        p = Path(path).expanduser().resolve()

        if p.is_file():
            try:
                content = p.read_text(errors="replace")
                all_files[str(p)] = content
            except (PermissionError, OSError) as e:
                all_files[str(p)] = f"[Error reading file: {e}]"
        elif p.is_dir():
            loaded = load_files(str(p))
            # Use full paths as keys
            for fn, content in loaded.items():
                all_files[str(p / fn)] = content
        else:
            all_files[str(p)] = f"[File not found: {path}]"

    if not all_files:
        return "No files found at the specified paths."

    # Configure compression
    config = TokenZipConfig(
        min_pattern_length=DEFAULT_CONFIG.min_pattern_length,
        min_pattern_frequency=DEFAULT_CONFIG.min_pattern_frequency,
        keep_todo_comments=DEFAULT_CONFIG.keep_todo_comments,
        keep_license_headers=DEFAULT_CONFIG.keep_license_headers,
        target_files=[target_file] if target_file else [],
    )

    # Run compression
    pipeline = CompressionPipeline(config)
    compressed = pipeline.compress_files(all_files)

    # Track savings
    stats = pipeline.stats
    orig_tokens = stats.original_tokens or count_tokens("\n".join(all_files.values())) or 0
    comp_tokens = stats.compressed_tokens or count_tokens("\n".join(compressed.values())) or 0

    tracker.record(
        files=list(all_files.keys()),
        original_tokens=orig_tokens,
        compressed_tokens=comp_tokens,
        original_chars=stats.original_chars,
        compressed_chars=stats.compressed_chars,
    )

    # Build output with codebook instructions
    output_parts = []

    # Add compression instructions for the model
    output_parts.append(CODEBOOK_INSTRUCTIONS)

    # Add compressed files
    for fn, content in sorted(compressed.items()):
        short_name = _shorten_path(fn)
        output_parts.append(f"--- {short_name} ---")
        output_parts.append(content)

    # Add savings footer
    savings_pct = stats.char_savings_pct
    output_parts.append("")
    output_parts.append(
        f"[TokenZip: {len(all_files)} files | "
        f"{orig_tokens:,}→{comp_tokens:,} tokens | "
        f"{savings_pct:.0f}% saved | "
        f"Session total: {tracker.total_tokens_saved:,} tokens saved]"
    )

    return "\n".join(output_parts)


@mcp.tool()
def compress_context(
    directory: str,
    target_file: str = "",
    file_extensions: list[str] | None = None,
) -> str:
    """Compress an entire directory of source files for context loading.

    Best for loading a full project or module as context. Applies all
    compression stages including cross-file deduplication.

    Args:
        directory: Path to the directory to compress.
        target_file: File you plan to edit (returned uncompressed). Optional.
        file_extensions: Only include files with these extensions (e.g., [".java", ".py"]).
                        Defaults to all supported extensions.
    """
    dir_path = Path(directory).expanduser().resolve()

    if not dir_path.is_dir():
        return f"Not a directory: {directory}"

    files = load_files(str(dir_path))

    if file_extensions:
        ext_set = set(file_extensions)
        files = {
            fn: content for fn, content in files.items()
            if any(fn.endswith(ext) for ext in ext_set)
        }

    if not files:
        return f"No supported files found in: {directory}"

    config = TokenZipConfig(
        min_pattern_length=DEFAULT_CONFIG.min_pattern_length,
        min_pattern_frequency=DEFAULT_CONFIG.min_pattern_frequency,
        keep_todo_comments=DEFAULT_CONFIG.keep_todo_comments,
        keep_license_headers=DEFAULT_CONFIG.keep_license_headers,
        target_files=[target_file] if target_file else [],
    )

    pipeline = CompressionPipeline(config)
    compressed = pipeline.compress_files(files)

    stats = pipeline.stats
    orig_tokens = stats.original_tokens or count_tokens("\n".join(files.values())) or 0
    comp_tokens = stats.compressed_tokens or count_tokens("\n".join(compressed.values())) or 0

    tracker.record(
        files=list(files.keys()),
        original_tokens=orig_tokens,
        compressed_tokens=comp_tokens,
        original_chars=stats.original_chars,
        compressed_chars=stats.compressed_chars,
    )

    output_parts = [CODEBOOK_INSTRUCTIONS]

    for fn, content in sorted(compressed.items()):
        output_parts.append(f"--- {fn} ---")
        output_parts.append(content)

    # Stage breakdown
    output_parts.append("")
    stage_info = " | ".join(
        f"{stage}: {saved:,}ch"
        for stage, saved in stats.stage_savings.items()
        if saved > 0
    )
    output_parts.append(
        f"[TokenZip: {len(files)} files | "
        f"{orig_tokens:,}→{comp_tokens:,} tokens ({stats.char_savings_pct:.0f}% saved) | "
        f"{stage_info}]"
    )
    output_parts.append(
        f"[Session total: {tracker.total_tokens_saved:,} tokens saved across "
        f"{tracker.num_compressions} operations]"
    )

    return "\n".join(output_parts)


@mcp.tool()
def session_savings() -> str:
    """Show cumulative token savings for this session.

    Call this anytime to see how many tokens TokenZip has saved
    across all file reads in the current conversation.
    """
    if tracker.num_compressions == 0:
        return "No compressions performed yet in this session."
    return tracker.summary()


# ── Helpers ──────────────────────────────────────────────────────


def _shorten_path(path: str) -> str:
    """Shorten an absolute path for display."""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


# ── Entry point ──────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
