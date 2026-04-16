"""Comment stripping compressor — removes comments while preserving code."""

import io
import re
import tokenize as py_tokenize

from tokenzip.compressors.base import BaseCompressor
from tokenzip.config import TokenZipConfig

# Language detection by file extension
LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".go": "go",
    ".rb": "ruby",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".rs": "rust",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".css": "css",
    ".scss": "css",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

# Languages that use // and /* */ comments
C_STYLE_LANGS = {
    "javascript",
    "typescript",
    "java",
    "c",
    "cpp",
    "go",
    "rust",
    "swift",
    "kotlin",
    "csharp",
    "php",
    "css",
    "scss",
}

# Languages that use # comments
HASH_COMMENT_LANGS = {"ruby", "shell", "yaml", "toml"}


def _detect_language(filename: str) -> str | None:
    """Detect language from file extension."""
    for ext, lang in LANG_MAP.items():
        if filename.endswith(ext):
            return lang
    return None


def _should_keep_comment(comment_text: str, config: TokenZipConfig) -> bool:
    """Check if a comment should be preserved based on config."""
    lower = comment_text.lower()

    if config.keep_license_headers:
        for marker in config.license_markers:
            if marker in lower:
                return True

    if config.keep_todo_comments:
        if any(tag in lower for tag in ("todo", "fixme", "hack", "xxx", "bug")):
            return True

    return False


def _strip_python_comments(source: str, config: TokenZipConfig) -> str:
    """Strip comments from Python source using the tokenize module.

    Uses tokenize to find comment positions, then directly edits the source
    lines. This avoids tokenize.untokenize which produces messy formatting.
    """
    try:
        tokens = list(
            py_tokenize.generate_tokens(io.StringIO(source).readline)
        )
    except py_tokenize.TokenError:
        return _strip_hash_comments(source, config)

    lines = source.split("\n")

    # Collect lines to remove entirely (standalone comments) and
    # inline comment positions to strip
    comment_lines_to_remove: set[int] = set()  # 0-indexed line numbers
    inline_comment_cuts: dict[int, int] = {}  # line_idx -> col to cut at
    docstring_lines_to_remove: set[int] = set()

    for tok in tokens:
        tok_type, tok_string, tok_start, tok_end, tok_line = tok

        if tok_type == py_tokenize.COMMENT:
            if _should_keep_comment(tok_string, config):
                continue

            line_idx = tok_start[0] - 1  # tokenize uses 1-based lines
            col = tok_start[1]

            # Check if comment is the only thing on this line
            line_before_comment = lines[line_idx][:col].strip()
            if not line_before_comment:
                comment_lines_to_remove.add(line_idx)
            else:
                inline_comment_cuts[line_idx] = col

        elif tok_type == py_tokenize.STRING:
            stripped = tok_string.strip()
            is_docstring = (
                stripped.startswith('"""')
                or stripped.startswith("'''")
                or stripped.startswith('r"""')
                or stripped.startswith("r'''")
            )
            if is_docstring and _is_standalone_docstring(tokens, tok):
                if not _should_keep_comment(tok_string, config):
                    for ln in range(tok_start[0] - 1, tok_end[0]):
                        docstring_lines_to_remove.add(ln)

    # Apply removals
    result_lines = []
    for i, line in enumerate(lines):
        if i in comment_lines_to_remove or i in docstring_lines_to_remove:
            continue
        if i in inline_comment_cuts:
            line = line[: inline_comment_cuts[i]].rstrip()
        result_lines.append(line)

    return "\n".join(result_lines)


def _is_standalone_docstring(tokens: list, target_tok) -> bool:
    """Check if a string token is a standalone docstring (not assigned to a variable)."""
    tok_type, tok_string, tok_start, tok_end, tok_line = target_tok

    # Find the index of this token
    for i, tok in enumerate(tokens):
        if tok[2] == tok_start and tok[3] == tok_end:
            # Check if previous meaningful token is NEWLINE, INDENT, or start of file
            for j in range(i - 1, -1, -1):
                prev_type = tokens[j][0]
                if prev_type in (
                    py_tokenize.NEWLINE,
                    py_tokenize.INDENT,
                    py_tokenize.ENCODING,
                    py_tokenize.NL,
                    py_tokenize.DEDENT,
                ):
                    return True
                elif prev_type in (
                    py_tokenize.COMMENT,
                ):
                    continue
                else:
                    return False
            return True
    return False


def _strip_c_style_comments(source: str, config: TokenZipConfig) -> str:
    """Strip // and /* */ comments from C-style languages.

    Uses a state machine to correctly handle strings and regex literals.
    """
    result = []
    i = 0
    length = len(source)
    in_single_quote = False
    in_double_quote = False
    in_template_literal = False

    while i < length:
        ch = source[i]

        # Handle escape sequences inside strings
        if (in_single_quote or in_double_quote or in_template_literal) and ch == "\\":
            result.append(ch)
            if i + 1 < length:
                result.append(source[i + 1])
                i += 2
            else:
                i += 1
            continue

        # Toggle string states
        if not in_double_quote and not in_template_literal and ch == "'":
            in_single_quote = not in_single_quote
            result.append(ch)
            i += 1
            continue

        if not in_single_quote and not in_template_literal and ch == '"':
            in_double_quote = not in_double_quote
            result.append(ch)
            i += 1
            continue

        if not in_single_quote and not in_double_quote and ch == "`":
            in_template_literal = not in_template_literal
            result.append(ch)
            i += 1
            continue

        # Skip comments only when outside strings
        if not in_single_quote and not in_double_quote and not in_template_literal:
            # Single-line comment
            if ch == "/" and i + 1 < length and source[i + 1] == "/":
                comment_start = i
                while i < length and source[i] != "\n":
                    i += 1
                comment_text = source[comment_start:i]
                if _should_keep_comment(comment_text, config):
                    result.append(comment_text)
                continue

            # Multi-line comment
            if ch == "/" and i + 1 < length and source[i + 1] == "*":
                comment_start = i
                i += 2
                while i + 1 < length and not (
                    source[i] == "*" and source[i + 1] == "/"
                ):
                    i += 1
                i += 2  # skip */
                comment_text = source[comment_start:i]
                if _should_keep_comment(comment_text, config):
                    result.append(comment_text)
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _strip_hash_comments(source: str, config: TokenZipConfig) -> str:
    """Strip # comments from Ruby, Shell, YAML, etc.

    Handles strings containing # correctly.
    """
    lines = source.split("\n")
    result = []

    for line in lines:
        stripped = _strip_hash_from_line(line, config)
        result.append(stripped)

    return "\n".join(result)


def _strip_hash_from_line(line: str, config: TokenZipConfig) -> str:
    """Remove # comment from a single line, respecting strings."""
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(line):
        ch = line[i]

        # Handle escapes
        if (in_single_quote or in_double_quote) and ch == "\\":
            i += 2
            continue

        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif ch == "#" and not in_single_quote and not in_double_quote:
            comment_text = line[i:]
            if _should_keep_comment(comment_text, config):
                return line
            return line[:i].rstrip()

        i += 1

    return line


def _strip_html_comments(source: str, config: TokenZipConfig) -> str:
    """Strip <!-- --> comments from HTML/XML."""

    def _replace_comment(match: re.Match) -> str:
        if _should_keep_comment(match.group(0), config):
            return match.group(0)
        return ""

    return re.sub(r"<!--[\s\S]*?-->", _replace_comment, source)


class CommentStripper(BaseCompressor):
    """Removes comments from source code files."""

    @property
    def name(self) -> str:
        return "comment_stripper"

    def compress(self, content: str, filename: str = "") -> str:
        lang = _detect_language(filename)

        if lang is None:
            return content

        if lang == "python":
            return _strip_python_comments(content, self.config)

        if lang in C_STYLE_LANGS:
            return _strip_c_style_comments(content, self.config)

        if lang in HASH_COMMENT_LANGS:
            return _strip_hash_comments(content, self.config)

        if lang in ("html", "xml"):
            return _strip_html_comments(content, self.config)

        return content
