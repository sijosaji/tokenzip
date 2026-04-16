# TokenZip

Text-domain compression for LLM prompts. Reduce token usage by 20-40% without losing context.

TokenZip compresses source code before it reaches the model — stripping comments, normalizing whitespace, deduplicating patterns across files, and building a codebook of repeated code fragments. The output stays in readable text so the LLM can understand it with zero quality loss.

## How It Works

```
Source files (raw)
       │
       ▼
┌─────────────────────────┐
│  1. Comment Stripper     │  Language-aware removal (15+ languages)
│  2. Whitespace Normalizer│  Collapse blanks, strip trailing spaces
│  3. RLE Compressor       │  "======" → "="*40
│  4. Dictionary Coder     │  AST-level pattern detection + codebook
│  5. Cross-file Dedup     │  Block dedup + delta encoding
└─────────────────────────┘
       │
       ▼
Codebook + Compressed text (LLM-readable)
```

The model receives a `[CODEBOOK]` header mapping short codes like `[D1]`, `[D2]` to their full text, followed by compressed code where repeated patterns are replaced with these references. All variable names, function names, and logic are preserved exactly.

## Results

| Project | Language | Files | Token Savings |
|---|---|---|---|
| Spring Boot auth service | Java | 26 | **24-43%** |
| TokenZip itself | Python | 16 | **26%** |
| React webapp | JSX | 31 | **10%** |

Compression is highest on languages with more boilerplate (Java, Go) and projects with repeated patterns across files.

## Installation

```bash
# Clone and install
git clone https://github.com/yourusername/tokenzip.git
cd tokenzip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

### CLI

```bash
# Compress a file
tokenzip compress path/to/file.py

# Compress a directory with stats
tokenzip compress path/to/project/ --stats

# Skip files you're editing (kept uncompressed)
tokenzip compress src/ --target src/main.py

# Just see compression stats
tokenzip stats path/to/project/
```

### MCP Server (Claude Code, Cline, Cursor)

TokenZip ships as an MCP server that integrates with any MCP-compatible AI coding tool.

**Add to Claude Code:**

```bash
claude mcp add -s user tokenzip /path/to/tokenzip/.venv/bin/tokenzip-mcp
```

**Add to Cline / Cursor** (in MCP settings):

```json
{
  "tokenzip": {
    "command": "/path/to/tokenzip/.venv/bin/tokenzip-mcp",
    "args": []
  }
}
```

**MCP Tools:**

| Tool | Description |
|---|---|
| `read_compressed` | Read files with compression. Use instead of raw file reads for context. |
| `compress_context` | Compress an entire directory for context loading. |
| `session_savings` | Show cumulative tokens saved in the current session. |

### Python API

```python
from tokenzip import CompressionPipeline, TokenZipConfig

# Compress multiple files
config = TokenZipConfig(min_pattern_length=20, min_pattern_frequency=2)
pipeline = CompressionPipeline(config)

files = {
    "service.py": open("service.py").read(),
    "models.py": open("models.py").read(),
}

compressed = pipeline.compress_files(files)
print(pipeline.stats.summary())
```

## Compressed Output Example

**Before** (raw Java, 2,208 tokens):

```java
package com.example.service;

import com.example.dto.AuthResponse;
import com.example.entity.UserCredential;
import com.example.repository.UserCredentialRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
// ... repeated across 5 files
```

**After** (compressed, 1,263 tokens — 43% saved):

```
[CODEBOOK]
# D1 = package com.example.service; | import com.example.dto.AuthResponse; | import com.example...
# D2 = import org.springframework.http.HttpStatus;
# D3 = import org.springframework.stereotype.Service;
[/CODEBOOK]

[D1]
[D2]
[D3]
// ... unique code preserved exactly
```

## Compression Techniques

### Safe (always applied)
- **Comment stripping** — language-aware removal using `tokenize` (Python) and tree-sitter state machines (JS/Java/Go/etc). Preserves `TODO`, `FIXME`, and license headers.
- **Whitespace normalization** — collapse blank lines, strip trailing spaces, preserve indentation.
- **RLE** — run-length encoding for repeated characters (`"======..."` becomes `"="*40`).

### Smart (AST-powered)
- **Dictionary coding** — tree-sitter extracts AST-level patterns (import blocks, annotated methods, structural blocks) across files, builds a codebook, replaces with `[D1]` references.
- **Cross-file deduplication** — identical blocks referenced instead of repeated; similar files expressed as deltas.

### Safety Guardrails
- Never compresses more than 50% of any single file
- Never modifies variable names, function names, or logic
- Never drops lines of code — only removes comments and whitespace
- Target files (files being edited) are returned uncompressed
- Codebook is always included so the model can look up any reference

## Supported Languages

Comment stripping and AST pattern detection support:

| Language | Comment Strip | AST Patterns |
|---|---|---|
| Python | tokenize module | tree-sitter |
| Java | state machine | tree-sitter |
| JavaScript/JSX | state machine | tree-sitter |
| TypeScript/TSX | state machine | tree-sitter |
| Go | state machine | tree-sitter |
| Ruby | regex | - |
| Shell/Bash | regex | - |
| Rust, Swift, Kotlin, C# | state machine | - |
| HTML/XML | regex | - |
| YAML, TOML | regex | - |
| CSS/SCSS | state machine | - |

## Configuration

```python
TokenZipConfig(
    # Comment stripper
    keep_license_headers=True,     # preserve copyright/license comments
    keep_todo_comments=True,       # preserve TODO/FIXME/HACK

    # Dictionary coder
    min_pattern_length=30,         # minimum chars for a pattern to qualify
    min_pattern_frequency=3,       # minimum occurrences across files
    max_dictionary_size=50,        # max codebook entries

    # Safety
    max_compression_ratio=0.50,    # never compress more than 50%
    target_files=["main.py"],      # files to skip (being edited)
)
```

## Project Structure

```
tokenzip/
├── pyproject.toml
├── tokenzip/
│   ├── __init__.py
│   ├── cli.py                           # CLI: tokenzip compress / stats
│   ├── config.py                        # Configuration dataclass
│   ├── pipeline.py                      # Main pipeline + file loader
│   ├── stats.py                         # Compression stats + token counting
│   ├── compressors/
│   │   ├── base.py                      # Base compressor interface
│   │   ├── comment_stripper.py          # Language-aware comment removal
│   │   ├── whitespace_normalizer.py     # Whitespace normalization
│   │   ├── rle_compressor.py            # Run-length encoding
│   │   ├── dictionary_coder.py          # LZ78-style codebook (AST + line-level)
│   │   ├── deduplicator.py              # Cross-file block dedup + delta encoding
│   │   └── ast_pattern_extractor.py     # Tree-sitter AST pattern extraction
│   └── mcp/
│       ├── server.py                    # MCP server (Claude Code, Cline, Cursor)
│       └── session_tracker.py           # Session-level savings tracking
└── tests/
    └── test_compressors.py              # 21 tests
```

## Development

```bash
git clone https://github.com/yourusername/tokenzip.git
cd tokenzip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

MIT
