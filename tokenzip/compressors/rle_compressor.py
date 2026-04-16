"""Run-Length Encoding compressor — compress repeated character sequences."""

import re

from tokenzip.compressors.base import BaseCompressor


class RLECompressor(BaseCompressor):
    """Applies text-domain RLE to repeated character runs."""

    @property
    def name(self) -> str:
        return "rle_compressor"

    def compress(self, content: str, filename: str = "") -> str:
        lines = content.split("\n")
        result = []

        for line in lines:
            result.append(self._compress_line(line))

        return "\n".join(result)

    def _compress_line(self, line: str) -> str:
        """Compress repeated characters in a single line."""
        min_run = self.config.min_run_length

        # Match runs of the same non-alphanumeric character (=, -, #, *, etc.)
        # We don't compress runs of letters/digits as they are usually meaningful
        def replace_run(match: re.Match) -> str:
            char = match.group(0)[0]
            count = len(match.group(0))
            if count >= min_run and not char.isalnum() and char != " ":
                return f'"{char}"*{count}'
            return match.group(0)

        # Find runs of repeated characters (same char 4+ times)
        pattern = rf"(.)\1{{{min_run - 1},}}"
        compressed = re.sub(pattern, replace_run, line)

        # Only use compressed version if it's actually shorter
        if len(compressed) < len(line):
            return compressed
        return line
