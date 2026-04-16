"""Dictionary coding compressor — LZ78-style pattern replacement with codebook.

Uses AST-level pattern extraction (tree-sitter) when available,
falls back to line-level matching otherwise.
"""

from collections import Counter

from tokenzip.compressors.base import BaseCompressor
from tokenzip.compressors.ast_pattern_extractor import (
    extract_patterns,
    find_repeated_patterns,
    detect_language,
    is_available as ast_available,
    ASTPattern,
)
from tokenzip.config import TokenZipConfig


class DictionaryCoder(BaseCompressor):
    """Finds repeated patterns across files, builds a codebook, replaces with short references.

    Two-tier approach:
    1. AST-level patterns (tree-sitter): import blocks, decorated methods,
       structural blocks, method bodies — catches semantic patterns.
    2. Line-level patterns (fallback): repeated lines/multi-line blocks —
       catches anything the AST misses.
    """

    def __init__(self, config: TokenZipConfig):
        super().__init__(config)
        self._codebook: dict[str, str] = {}  # pattern -> code (e.g., "D1")
        self._reverse_codebook: dict[str, str] = {}  # code -> pattern

    @property
    def name(self) -> str:
        return "dictionary_coder"

    @property
    def codebook(self) -> dict[str, str]:
        """Returns the code -> pattern mapping for the codebook header."""
        return dict(self._reverse_codebook)

    def compress(self, content: str, filename: str = "") -> str:
        """Single-file compression using already-built codebook."""
        if not self._codebook:
            return content
        return self._apply_codebook(content)

    def compress_multi(self, files: dict[str, str]) -> dict[str, str]:
        """Multi-file compression: scan all files, build codebook, then compress."""
        self._build_codebook(files)

        if not self._codebook:
            return files

        return {fn: self._apply_codebook(content) for fn, content in files.items()}

    def _build_codebook(self, files: dict[str, str]):
        """Build codebook using AST patterns + line-level fallback."""
        min_len = self.config.min_pattern_length
        min_freq = self.config.min_pattern_frequency
        max_entries = self.config.max_dictionary_size

        scored: list[tuple[int, str, int]] = []

        # ── Tier 1: AST-level patterns (if tree-sitter is available) ──
        if ast_available():
            ast_patterns = self._extract_ast_patterns(files)
            pattern_groups = find_repeated_patterns(
                ast_patterns,
                min_frequency=min_freq,
                min_length=min_len,
            )

            for group in pattern_groups:
                savings = group.total_chars_saved
                if savings > 0:
                    scored.append((savings, group.canonical, group.count))

        # ── Tier 2: Line-level patterns (catches what AST misses) ──
        line_scored = self._find_line_patterns(files, min_len, min_freq)
        scored.extend(line_scored)

        if not scored:
            return

        # Sort by savings (highest first)
        scored.sort(reverse=True)

        # Build codebook, avoiding overlapping patterns
        self._codebook = {}
        self._reverse_codebook = {}
        code_index = 1

        for _, pattern, count in scored[:max_entries * 2]:  # consider more, pick best
            if len(self._codebook) >= max_entries:
                break

            # Skip if this pattern overlaps with an already-selected pattern
            skip = False
            for existing_pat in self._codebook:
                if pattern in existing_pat or existing_pat in pattern:
                    skip = True
                    break
            if skip:
                continue

            # Skip patterns that are too short to be worth a codebook entry
            code = f"D{code_index}"
            # Net savings: (pattern_len - code_len_with_brackets) * (count - 1)
            # We keep one occurrence conceptually, replace the rest
            code_with_brackets = f"[{code}]"
            net_savings = (len(pattern) - len(code_with_brackets)) * (count - 1)
            if net_savings < 10:
                continue

            self._codebook[pattern] = code
            self._reverse_codebook[code] = pattern
            code_index += 1

    def _extract_ast_patterns(self, files: dict[str, str]) -> list[ASTPattern]:
        """Extract AST patterns from all files."""
        all_patterns: list[ASTPattern] = []

        for fn, content in files.items():
            lang = detect_language(fn)
            if lang is None:
                continue

            patterns = extract_patterns(content, fn, lang)
            all_patterns.extend(patterns)

        return all_patterns

    def _find_line_patterns(
        self,
        files: dict[str, str],
        min_len: int,
        min_freq: int,
    ) -> list[tuple[int, str, int]]:
        """Find repeated line-level patterns (fallback tier)."""
        pattern_counts: Counter[str] = Counter()

        # Single lines
        for fn, content in files.items():
            for line in content.split("\n"):
                stripped = line.strip()
                if len(stripped) >= min_len:
                    pattern_counts[stripped] += 1

        # Multi-line blocks (2-5 lines)
        for fn, content in files.items():
            lines = content.split("\n")
            for block_size in range(2, 6):
                for i in range(len(lines) - block_size + 1):
                    block = "\n".join(
                        line.strip() for line in lines[i : i + block_size]
                    )
                    if len(block) >= min_len:
                        pattern_counts[block] += 1

        scored = []
        for pat, count in pattern_counts.items():
            if count < min_freq:
                continue
            code_len = 5  # "[D1]"
            savings = (len(pat) - code_len) * count
            if savings > 0:
                scored.append((savings, pat, count))

        return scored

    def _apply_codebook(self, content: str) -> str:
        """Replace patterns in content with their codebook references."""
        if not self._codebook:
            return content

        # Sort by pattern length (longest first) to avoid partial matches
        sorted_patterns = sorted(self._codebook.keys(), key=len, reverse=True)

        result = content

        for pattern in sorted_patterns:
            code = self._codebook[pattern]

            if "\n" in pattern:
                # Multi-line pattern: direct replacement
                result = result.replace(pattern, f"[{code}]")

                # Also try with normalized whitespace
                normalized = "\n".join(line.strip() for line in pattern.split("\n"))
                lines = result.split("\n")
                i = 0
                new_lines = []
                while i < len(lines):
                    # Try to match normalized block starting at this line
                    matched = False
                    pat_lines = pattern.split("\n")
                    if i + len(pat_lines) <= len(lines):
                        candidate = "\n".join(
                            lines[j].strip() for j in range(i, i + len(pat_lines))
                        )
                        if candidate == normalized:
                            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
                            new_lines.append(f"{indent}[{code}]")
                            i += len(pat_lines)
                            matched = True

                    if not matched:
                        new_lines.append(lines[i])
                        i += 1

                result = "\n".join(new_lines)
            else:
                # Single-line pattern: replace preserving indentation
                lines = result.split("\n")
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped == pattern:
                        indent = line[: len(line) - len(line.lstrip())]
                        new_lines.append(f"{indent}[{code}]")
                    elif pattern in stripped:
                        new_lines.append(line.replace(pattern, f"[{code}]"))
                    else:
                        new_lines.append(line)
                result = "\n".join(new_lines)

        return result

    def format_codebook_header(self) -> str:
        """Generate the codebook header to prepend to compressed output."""
        if not self._reverse_codebook:
            return ""

        lines = ["[CODEBOOK]"]
        for code, pattern in sorted(
            self._reverse_codebook.items(),
            key=lambda x: int(x[0][1:]),  # sort D1, D2, ... numerically
        ):
            display = pattern.replace("\n", " | ")
            if len(display) > 120:
                display = display[:117] + "..."
            lines.append(f"# {code} = {display}")
        lines.append("[/CODEBOOK]")
        lines.append("")

        return "\n".join(lines)
