# TokenZip — Development Guide

## What is this project?

TokenZip is a text-domain compression tool for LLM prompts. It reduces token usage by 20-40% while preserving all code logic and structure. It works as a CLI tool, Python library, and MCP server.

## Architecture

The compression pipeline runs 5 stages in order:
1. **Comment Stripper** (`compressors/comment_stripper.py`) — language-aware comment removal using Python's `tokenize` module and tree-sitter-based state machines
2. **Whitespace Normalizer** (`compressors/whitespace_normalizer.py`) — collapse blank lines, strip trailing spaces
3. **RLE Compressor** (`compressors/rle_compressor.py`) — run-length encoding for repeated non-alphanumeric characters
4. **Dictionary Coder** (`compressors/dictionary_coder.py`) — two-tier pattern detection:
   - Tier 1: AST-level patterns via tree-sitter (`ast_pattern_extractor.py`) — import blocks, decorated methods, structural blocks
   - Tier 2: Line-level patterns (fallback) — repeated lines and multi-line blocks
5. **Deduplicator** (`compressors/deduplicator.py`) — cross-file block dedup and delta encoding for similar files

All compressors extend `BaseCompressor` and implement `compress()` for single files and optionally `compress_multi()` for cross-file operations.

## Key files

- `pipeline.py` — orchestrates all compressors, tracks stats, applies safety guardrails
- `config.py` — `TokenZipConfig` dataclass with all tunable parameters
- `stats.py` — compression statistics and token counting (tiktoken)
- `mcp/server.py` — MCP server with `read_compressed`, `compress_context`, `session_savings` tools
- `mcp/session_tracker.py` — tracks cumulative token savings across a session
- `cli.py` — CLI entry points (`tokenzip compress`, `tokenzip stats`)

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

All 21 tests should pass. Tests cover each compressor individually and the full pipeline.

## Safety rules

- Never compress more than 50% of any single file (configurable via `max_compression_ratio`)
- Never modify identifiers (variable names, function names, class names)
- Never drop code lines — only remove comments and whitespace noise
- Target files (files being edited) must be returned uncompressed
- Codebook must always be included when dictionary coding is used
- Dictionary entries must save more chars than the codebook overhead costs

## Adding a new language

1. Install the tree-sitter grammar: `pip install tree-sitter-{language}`
2. Add grammar loader in `ast_pattern_extractor.py` → `_load_grammar()`
3. Add node type mapping in `NODE_MAPPINGS` dict (~10 lines)
4. Add file extension mapping in `EXT_TO_LANG` dict
5. For comment stripping, add extension to `LANG_MAP` in `comment_stripper.py` and assign to the appropriate comment style (`C_STYLE_LANGS` or `HASH_COMMENT_LANGS`)

## MCP Server

The MCP server (`tokenzip-mcp`) runs over stdio. It exposes 3 tools:
- `read_compressed` — read files with compression applied
- `compress_context` — compress a full directory
- `session_savings` — show cumulative savings

Session state (savings tracker) lives in-memory for the lifetime of the MCP server process.
