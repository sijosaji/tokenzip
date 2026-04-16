"""AST-level pattern extraction using tree-sitter.

Language-agnostic pattern detection: same algorithm for all languages,
only the node-type mapping config differs per language.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

try:
    from tree_sitter import Language, Parser, Node

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False

# ── Language grammar loaders ─────────────────────────────────────

_GRAMMAR_LOADERS = {}


def _load_grammar(lang: str) -> Language | None:
    """Lazily load a tree-sitter grammar."""
    if lang in _GRAMMAR_LOADERS:
        return _GRAMMAR_LOADERS[lang]

    try:
        if lang == "python":
            import tree_sitter_python as mod
        elif lang == "java":
            import tree_sitter_java as mod
        elif lang == "javascript":
            import tree_sitter_javascript as mod
        elif lang == "typescript":
            import tree_sitter_typescript as mod

            # typescript package has both typescript and tsx
            _GRAMMAR_LOADERS["typescript"] = Language(mod.language_typescript())
            _GRAMMAR_LOADERS["tsx"] = Language(mod.language_tsx())
            return _GRAMMAR_LOADERS.get(lang)
        elif lang == "tsx":
            import tree_sitter_typescript as mod

            _GRAMMAR_LOADERS["tsx"] = Language(mod.language_tsx())
            _GRAMMAR_LOADERS["typescript"] = Language(mod.language_typescript())
            return _GRAMMAR_LOADERS.get(lang)
        elif lang == "go":
            import tree_sitter_go as mod
        else:
            _GRAMMAR_LOADERS[lang] = None
            return None

        _GRAMMAR_LOADERS[lang] = Language(mod.language())
        return _GRAMMAR_LOADERS[lang]
    except ImportError:
        _GRAMMAR_LOADERS[lang] = None
        return None


# ── Node type mappings (the only language-specific config) ───────

# Maps our generic concept names to tree-sitter node types per language.
NODE_MAPPINGS: dict[str, dict[str, list[str]]] = {
    "python": {
        "function": ["function_definition"],
        "class": ["class_definition"],
        "import": ["import_statement", "import_from_statement"],
        "decorator": ["decorator"],
        "block": ["block"],
        "if": ["if_statement"],
        "try": ["try_statement"],
        "for": ["for_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment", "augmented_assignment"],
        "call": ["call"],
    },
    "java": {
        "function": ["method_declaration", "constructor_declaration"],
        "class": ["class_declaration", "interface_declaration", "enum_declaration"],
        "import": ["import_declaration"],
        "decorator": ["marker_annotation", "annotation"],
        "block": ["block"],
        "if": ["if_statement"],
        "try": ["try_statement"],
        "for": ["for_statement", "enhanced_for_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment_expression"],
        "call": ["method_invocation"],
        "field": ["field_declaration"],
    },
    "javascript": {
        "function": [
            "function_declaration",
            "method_definition",
            "arrow_function",
        ],
        "class": ["class_declaration"],
        "import": ["import_statement"],
        "decorator": ["decorator"],
        "block": ["statement_block"],
        "if": ["if_statement"],
        "try": ["try_statement"],
        "for": ["for_statement", "for_in_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment_expression"],
        "call": ["call_expression"],
        "export": ["export_statement"],
    },
    "typescript": {
        "function": [
            "function_declaration",
            "method_definition",
            "arrow_function",
        ],
        "class": ["class_declaration"],
        "import": ["import_statement"],
        "decorator": ["decorator"],
        "block": ["statement_block"],
        "if": ["if_statement"],
        "try": ["try_statement"],
        "for": ["for_statement", "for_in_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment_expression"],
        "call": ["call_expression"],
        "export": ["export_statement"],
        "interface": ["interface_declaration"],
        "type_alias": ["type_alias_declaration"],
    },
    "tsx": {
        "function": [
            "function_declaration",
            "method_definition",
            "arrow_function",
        ],
        "class": ["class_declaration"],
        "import": ["import_statement"],
        "decorator": ["decorator"],
        "block": ["statement_block"],
        "if": ["if_statement"],
        "try": ["try_statement"],
        "for": ["for_statement", "for_in_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment_expression"],
        "call": ["call_expression"],
        "export": ["export_statement"],
    },
    "go": {
        "function": ["function_declaration", "method_declaration"],
        "class": ["type_declaration"],
        "import": ["import_declaration"],
        "block": ["block"],
        "if": ["if_statement"],
        "for": ["for_statement"],
        "return": ["return_statement"],
        "assignment": ["assignment_statement", "short_var_declaration"],
        "call": ["call_expression"],
        "defer": ["defer_statement"],
    },
}

# File extension to language mapping
EXT_TO_LANG = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


# ── Data structures ──────────────────────────────────────────────


@dataclass
class ASTPattern:
    """A structural pattern extracted from the AST."""

    kind: str  # "import_block", "decorated_method", "method_signature", "structural_block"
    text: str  # the actual source text of this pattern
    normalized: str  # normalized version for comparison (stripped whitespace)
    filename: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass
class PatternGroup:
    """A group of identical/similar patterns found across files."""

    canonical: str  # the pattern text to use in the codebook
    occurrences: list[ASTPattern] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def total_chars_saved(self) -> int:
        """Estimate chars saved by replacing all occurrences with a short code."""
        code_len = 5  # e.g., "[D1]"
        return sum(len(occ.text) - code_len for occ in self.occurrences[1:])


# ── Core extraction logic (language-agnostic) ────────────────────


def detect_language(filename: str) -> str | None:
    """Detect language from file extension."""
    for ext, lang in EXT_TO_LANG.items():
        if filename.endswith(ext):
            return lang
    return None


def parse_file(content: str, lang: str) -> Node | None:
    """Parse source code into a tree-sitter AST."""
    if not _TREE_SITTER_AVAILABLE:
        return None

    grammar = _load_grammar(lang)
    if grammar is None:
        return None

    parser = Parser(grammar)
    tree = parser.parse(content.encode("utf-8"))
    return tree.root_node


def _find_nodes(node: Node, target_types: list[str]) -> list[Node]:
    """Recursively find all nodes of the given types."""
    results = []
    if node.type in target_types:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes(child, target_types))
    return results


def _node_text(node: Node, source: bytes) -> str:
    """Extract the source text for a node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    """Normalize text for pattern comparison: strip and collapse whitespace."""
    lines = [line.strip() for line in text.strip().split("\n")]
    return "\n".join(lines)


def extract_patterns(
    content: str,
    filename: str,
    lang: str | None = None,
) -> list[ASTPattern]:
    """Extract compressible AST patterns from a single file.

    This is the main extraction function — completely language-agnostic.
    The language only determines which node types to look for.
    """
    if lang is None:
        lang = detect_language(filename)
    if lang is None or lang not in NODE_MAPPINGS:
        return []

    root = parse_file(content, lang)
    if root is None:
        return []

    source = content.encode("utf-8")
    mapping = NODE_MAPPINGS[lang]
    patterns: list[ASTPattern] = []

    # 1. Import blocks — group consecutive imports
    patterns.extend(_extract_import_blocks(root, source, mapping, filename))

    # 2. Decorated/annotated method signatures
    patterns.extend(_extract_decorated_methods(root, source, mapping, filename, lang))

    # 3. Method/function signatures (without body)
    patterns.extend(_extract_method_signatures(root, source, mapping, filename, lang))

    # 4. Repeated structural blocks (if/try/for with similar structure)
    patterns.extend(_extract_structural_blocks(root, source, mapping, filename))

    # 5. Field declarations (Java) / class-level assignments
    patterns.extend(_extract_field_patterns(root, source, mapping, filename))

    return patterns


def _extract_import_blocks(
    root: Node,
    source: bytes,
    mapping: dict,
    filename: str,
) -> list[ASTPattern]:
    """Group consecutive import statements into blocks."""
    import_nodes = _find_nodes(root, mapping.get("import", []))

    if not import_nodes:
        return []

    # Group consecutive imports
    blocks: list[list[Node]] = []
    current_block: list[Node] = [import_nodes[0]]

    for i in range(1, len(import_nodes)):
        prev = import_nodes[i - 1]
        curr = import_nodes[i]
        # Consecutive if within 2 lines of each other
        if curr.start_point[0] - prev.end_point[0] <= 2:
            current_block.append(curr)
        else:
            blocks.append(current_block)
            current_block = [curr]

    blocks.append(current_block)

    patterns = []
    for block in blocks:
        if len(block) < 2:
            continue

        text = _node_text_range(block[0], block[-1], source)
        if len(text) < 20:
            continue

        patterns.append(ASTPattern(
            kind="import_block",
            text=text,
            normalized=_normalize(text),
            filename=filename,
            start_line=block[0].start_point[0],
            end_line=block[-1].end_point[0],
        ))

    return patterns


def _extract_decorated_methods(
    root: Node,
    source: bytes,
    mapping: dict,
    filename: str,
    lang: str,
) -> list[ASTPattern]:
    """Extract decorator/annotation + method signature combos."""
    decorator_types = mapping.get("decorator", [])
    function_types = mapping.get("function", [])

    if not decorator_types or not function_types:
        return []

    patterns = []

    for func_node in _find_nodes(root, function_types):
        # Look for decorators/annotations that precede this function
        decorators = []
        if func_node.parent:
            for sibling in func_node.parent.children:
                if sibling.type in decorator_types and sibling.end_point[0] < func_node.start_point[0]:
                    # Check if this decorator is right before our function
                    if func_node.start_point[0] - sibling.end_point[0] <= 1:
                        decorators.append(sibling)

        # For Java, decorators are children of the method node itself (modifiers)
        if lang == "java":
            for child in func_node.children:
                if child.type in decorator_types:
                    decorators.append(child)

        if not decorators:
            continue

        # Build pattern: decorators + function signature (no body)
        sig = _extract_signature_text(func_node, source, lang)
        if not sig:
            continue

        dec_texts = [_node_text(d, source) for d in decorators]
        full_pattern = "\n".join(dec_texts) + "\n" + sig

        if len(full_pattern) < 15:
            continue

        patterns.append(ASTPattern(
            kind="decorated_method",
            text=full_pattern,
            normalized=_normalize(full_pattern),
            filename=filename,
            start_line=decorators[0].start_point[0],
            end_line=func_node.start_point[0],
        ))

    return patterns


def _extract_method_signatures(
    root: Node,
    source: bytes,
    mapping: dict,
    filename: str,
    lang: str,
) -> list[ASTPattern]:
    """Extract function/method signatures (name + params, no body)."""
    function_types = mapping.get("function", [])
    patterns = []

    for func_node in _find_nodes(root, function_types):
        full_text = _node_text(func_node, source)

        # Only worth compressing if the full method is substantial
        if len(full_text) < 30:
            continue

        # Extract just the signature
        sig = _extract_signature_text(func_node, source, lang)
        if not sig:
            continue

        # We want the full method text for pattern matching (not just signature)
        # The signature is used for grouping similar methods
        patterns.append(ASTPattern(
            kind="method_body",
            text=full_text,
            normalized=_normalize(full_text),
            filename=filename,
            start_line=func_node.start_point[0],
            end_line=func_node.end_point[0],
        ))

    return patterns


def _extract_structural_blocks(
    root: Node,
    source: bytes,
    mapping: dict,
    filename: str,
) -> list[ASTPattern]:
    """Extract repeated structural blocks (if/try/for patterns)."""
    patterns = []

    for block_type in ("if", "try", "for"):
        node_types = mapping.get(block_type, [])
        if not node_types:
            continue

        for node in _find_nodes(root, node_types):
            text = _node_text(node, source)
            if len(text) < 30:
                continue

            patterns.append(ASTPattern(
                kind=f"{block_type}_block",
                text=text,
                normalized=_normalize(text),
                filename=filename,
                start_line=node.start_point[0],
                end_line=node.end_point[0],
            ))

    return patterns


def _extract_field_patterns(
    root: Node,
    source: bytes,
    mapping: dict,
    filename: str,
) -> list[ASTPattern]:
    """Extract field declarations / class-level assignments."""
    patterns = []

    for concept in ("field", "assignment"):
        node_types = mapping.get(concept, [])
        if not node_types:
            continue

        for node in _find_nodes(root, node_types):
            text = _node_text(node, source)
            if len(text) < 30:
                continue

            patterns.append(ASTPattern(
                kind=concept,
                text=text,
                normalized=_normalize(text),
                filename=filename,
                start_line=node.start_point[0],
                end_line=node.end_point[0],
            ))

    return patterns


def _extract_signature_text(func_node: Node, source: bytes, lang: str) -> str:
    """Extract the signature portion of a function node (before the body)."""
    body_types = {
        "block",
        "statement_block",
        "expression_statement",
        "constructor_body",
        "method_body",
    }

    for child in func_node.children:
        if child.type in body_types:
            # Everything before the body is the signature
            sig = source[func_node.start_byte:child.start_byte].decode(
                "utf-8", errors="replace"
            ).rstrip()
            return sig

    # Fallback: take the first line
    full = _node_text(func_node, source)
    first_line = full.split("\n")[0]
    return first_line


def _node_text_range(start_node: Node, end_node: Node, source: bytes) -> str:
    """Extract text spanning from start_node to end_node."""
    return source[start_node.start_byte:end_node.end_byte].decode(
        "utf-8", errors="replace"
    )


# ── Cross-file pattern grouping ─────────────────────────────────


def find_repeated_patterns(
    all_patterns: list[ASTPattern],
    min_frequency: int = 2,
    min_length: int = 20,
) -> list[PatternGroup]:
    """Group identical patterns across files.

    Uses normalized text for comparison so whitespace differences
    don't prevent matching.
    """
    # Group by normalized text
    groups: dict[str, list[ASTPattern]] = {}
    for pat in all_patterns:
        if len(pat.normalized) < min_length:
            continue
        key = pat.normalized
        if key not in groups:
            groups[key] = []
        groups[key].append(pat)

    # Filter to patterns with enough occurrences
    result = []
    for normalized, occurrences in groups.items():
        if len(occurrences) < min_frequency:
            continue

        # Use the first occurrence's text as canonical
        group = PatternGroup(
            canonical=occurrences[0].text,
            occurrences=occurrences,
        )

        if group.total_chars_saved > 0:
            result.append(group)

    # Sort by total savings (most valuable first)
    result.sort(key=lambda g: g.total_chars_saved, reverse=True)

    return result


def is_available() -> bool:
    """Check if tree-sitter is available."""
    return _TREE_SITTER_AVAILABLE
