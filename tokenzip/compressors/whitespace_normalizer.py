"""Whitespace normalization — collapse redundant whitespace without breaking structure."""

import re

from tokenzip.compressors.base import BaseCompressor


class WhitespaceNormalizer(BaseCompressor):
    """Normalizes whitespace: collapses blank lines, strips trailing spaces."""

    @property
    def name(self) -> str:
        return "whitespace_normalizer"

    def compress(self, content: str, filename: str = "") -> str:
        # Strip trailing whitespace from each line
        lines = content.split("\n")
        lines = [line.rstrip() for line in lines]

        # Collapse 3+ consecutive blank lines into 1 blank line
        result = []
        blank_count = 0

        for line in lines:
            if line == "":
                blank_count += 1
                if blank_count <= 1:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)

        # Remove leading blank lines
        while result and result[0] == "":
            result.pop(0)

        # Remove trailing blank lines
        while result and result[-1] == "":
            result.pop()

        content = "\n".join(result)

        # Collapse multiple spaces within a line (but NOT leading indentation)
        content = re.sub(r"(?<=\S) {2,}(?=\S)", " ", content)

        return content
