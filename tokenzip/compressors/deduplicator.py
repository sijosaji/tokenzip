"""Cross-file deduplication — detect and reference repeated blocks across files."""

import hashlib
from collections import defaultdict
from difflib import SequenceMatcher

from tokenzip.compressors.base import BaseCompressor
from tokenzip.config import TokenZipConfig


def _hash_block(lines: list[str]) -> str:
    """Create a hash for a block of lines (ignoring leading whitespace)."""
    normalized = "\n".join(line.strip() for line in lines)
    return hashlib.md5(normalized.encode()).hexdigest()


def _similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


class Deduplicator(BaseCompressor):
    """Detects repeated blocks across files and replaces duplicates with references."""

    @property
    def name(self) -> str:
        return "deduplicator"

    def compress(self, content: str, filename: str = "") -> str:
        """Single file — no dedup possible."""
        return content

    def compress_multi(self, files: dict[str, str]) -> dict[str, str]:
        """Cross-file deduplication.

        1. Block-level dedup: find identical blocks across files
        2. File-level similarity: detect near-duplicate files and use delta notation
        """
        if len(files) < 2:
            return files

        result = dict(files)

        # Phase 1: Block-level deduplication
        result = self._dedup_blocks(result)

        # Phase 2: File-level delta encoding for very similar files
        result = self._delta_encode_similar_files(result)

        return result

    def _dedup_blocks(self, files: dict[str, str]) -> dict[str, str]:
        """Find identical multi-line blocks across files and reference them."""
        min_block = self.config.min_block_size

        # Build a map of block_hash -> [(filename, start_line, end_line)]
        block_locations: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)

        for fn, content in files.items():
            lines = content.split("\n")
            # Try block sizes from largest to smallest
            for block_size in range(min(20, len(lines)), min_block - 1, -1):
                for start in range(len(lines) - block_size + 1):
                    block_lines = lines[start : start + block_size]
                    # Skip blocks that are mostly empty
                    non_empty = sum(1 for l in block_lines if l.strip())
                    if non_empty < min_block:
                        continue

                    block_hash = _hash_block(block_lines)
                    block_text = "\n".join(block_lines)
                    block_locations[block_hash].append(
                        (fn, start, start + block_size, block_text)
                    )

        # Find blocks that appear in multiple files
        cross_file_blocks = {}
        for block_hash, locations in block_locations.items():
            # Get unique filenames
            unique_files = set(loc[0] for loc in locations)
            if len(unique_files) >= 2:
                # Use the first occurrence as the reference
                ref = locations[0]
                block_text = ref[3]
                # Only dedup if the block is substantial
                if len(block_text) >= self.config.min_pattern_length:
                    cross_file_blocks[block_hash] = {
                        "ref_file": ref[0],
                        "ref_start": ref[1],
                        "text": block_text,
                        "locations": locations[1:],  # all non-reference locations
                    }

        # Apply deduplication — replace duplicate blocks with references
        # Sort by block size (largest first) to avoid nested replacements
        sorted_blocks = sorted(
            cross_file_blocks.values(),
            key=lambda b: len(b["text"]),
            reverse=True,
        )

        replaced_ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
        result = dict(files)

        for block_info in sorted_blocks:
            ref_file = block_info["ref_file"]

            for fn, start, end, text in block_info["locations"]:
                if fn == ref_file:
                    continue

                # Check if this range overlaps with an already-replaced range
                overlaps = False
                for r_start, r_end in replaced_ranges[fn]:
                    if start < r_end and end > r_start:
                        overlaps = True
                        break
                if overlaps:
                    continue

                # Replace the block with a reference
                lines = result[fn].split("\n")
                ref_note = f"[same as {ref_file}:{start + 1}-{end}]"
                lines[start:end] = [ref_note]
                result[fn] = "\n".join(lines)

                # Track replaced range (adjusted for the replacement)
                replaced_ranges[fn].append((start, end))

        return result

    def _delta_encode_similar_files(self, files: dict[str, str]) -> dict[str, str]:
        """For very similar files, express one as delta from the other."""
        threshold = self.config.similarity_threshold
        filenames = list(files.keys())
        result = dict(files)
        delta_encoded: set[str] = set()

        for i in range(len(filenames)):
            if filenames[i] in delta_encoded:
                continue

            for j in range(i + 1, len(filenames)):
                if filenames[j] in delta_encoded:
                    continue

                sim = _similarity(files[filenames[i]], files[filenames[j]])

                if sim >= threshold:
                    # Express file j as delta from file i
                    delta = self._compute_delta(
                        filenames[i],
                        files[filenames[i]],
                        filenames[j],
                        files[filenames[j]],
                    )
                    result[filenames[j]] = delta
                    delta_encoded.add(filenames[j])

        return result

    def _compute_delta(
        self,
        ref_name: str,
        ref_content: str,
        target_name: str,
        target_content: str,
    ) -> str:
        """Compute a human-readable delta between two similar files."""
        ref_lines = ref_content.split("\n")
        target_lines = target_content.split("\n")

        matcher = SequenceMatcher(None, ref_lines, target_lines)

        delta_parts = [f"[delta from {ref_name}]"]
        has_changes = False

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                # Summarize equal blocks
                count = i2 - i1
                if count <= 3:
                    for line in ref_lines[i1:i2]:
                        delta_parts.append(line)
                else:
                    delta_parts.append(f"[lines {i1 + 1}-{i2}: same as {ref_name}]")
            elif op == "replace":
                has_changes = True
                for line in target_lines[j1:j2]:
                    delta_parts.append(line)
            elif op == "insert":
                has_changes = True
                delta_parts.append(f"[+inserted at line {i1 + 1}:]")
                for line in target_lines[j1:j2]:
                    delta_parts.append(line)
            elif op == "delete":
                has_changes = True
                delta_parts.append(f"[-removed lines {i1 + 1}-{i2} from {ref_name}]")

        if not has_changes:
            return f"[identical to {ref_name}]"

        return "\n".join(delta_parts)
