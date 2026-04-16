# TokenZip

**Cut your AI token bill by 20-40%. Automatically.**

## The Problem

Every time an AI coding tool (Claude Code, Cursor, Copilot, Cline) reads your code, it consumes tokens. Reading 10-15 files for context can cost thousands of tokens — and most of that is comments, repeated imports, boilerplate, and duplicated patterns across files. You're paying for noise.

For startups and teams running hundreds of AI-assisted tasks per day, this adds up fast.

## The Solution

TokenZip compresses your code **before** it reaches the AI model. It removes the noise, finds repeated patterns across files, and replaces them with short references — like a zip file, but the AI can still read it.

Your code logic, variable names, and structure stay exactly the same. The AI understands the compressed version perfectly using a lookup table (codebook) we include at the top.

**Before:** 2,208 tokens  
**After:** 1,263 tokens (43% saved)

## Real-World Results

| Project | Language | Token Savings |
|---|---|---|
| Spring Boot microservice | Java | **24-43%** |
| Python CLI tool | Python | **26%** |

Savings grow with project size — more files means more repeated patterns to compress.

## Quick Setup

```bash
git clone https://github.com/sijosaji/tokenzip.git
cd tokenzip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## How to Use

### Command Line

```bash
# See how much you'd save on a project
tokenzip stats path/to/your/project/

# Compress and see the output
tokenzip compress path/to/your/project/ --stats
```

### With AI Coding Tools (Claude Code, Cline, Cursor)

TokenZip runs as an MCP server — a plugin that AI tools can call automatically.

**Claude Code:**
```bash
claude mcp add -s user tokenzip /path/to/tokenzip/.venv/bin/tokenzip-mcp
```

**Cline / Cursor** (add to MCP settings):
```json
{
  "tokenzip": {
    "command": "/path/to/tokenzip/.venv/bin/tokenzip-mcp",
    "args": []
  }
}
```

Once connected, the AI gets 3 tools:
- **read_compressed** — read files with compression (use for context)
- **compress_context** — compress a whole directory
- **session_savings** — see how many tokens you've saved so far

### Python API

```python
from tokenzip import CompressionPipeline, TokenZipConfig

config = TokenZipConfig()
pipeline = CompressionPipeline(config)

files = {
    "service.py": open("service.py").read(),
    "models.py": open("models.py").read(),
}

compressed = pipeline.compress_files(files)
print(pipeline.stats.summary())
```

## What It Actually Does

Think of it like this — your code has a lot of repeated "noise":

```java
// Before: this block appears in 5 files
import com.example.dto.AuthResponse;
import com.example.entity.UserCredential;
import com.example.repository.UserCredentialRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
```

TokenZip replaces it with a short code and puts the original in a lookup table:

```
[CODEBOOK]
# D1 = import com.example.dto.AuthResponse; | import com.example.entity...
[/CODEBOOK]

[D1]   ← the AI looks this up in the codebook above
```

It also strips comments (the AI doesn't need `// initialize database connection` to understand `db.init()`), removes extra blank lines, and compresses repeated characters.

**Supports 15+ languages** including Python, Java, JavaScript, TypeScript, Go, Ruby, Rust, C#, and more.

## Safety

- Never changes your actual files — compression only happens in memory
- Never removes code logic — only comments and whitespace
- Never renames variables or functions
- Files you're editing are kept uncompressed so edits work correctly

## Run Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v   # 21 tests
```

## License

MIT
