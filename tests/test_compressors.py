"""Tests for individual compressors and the full pipeline."""

import pytest

from tokenzip.config import TokenZipConfig
from tokenzip.compressors.comment_stripper import CommentStripper
from tokenzip.compressors.whitespace_normalizer import WhitespaceNormalizer
from tokenzip.compressors.rle_compressor import RLECompressor
from tokenzip.compressors.dictionary_coder import DictionaryCoder
from tokenzip.compressors.deduplicator import Deduplicator
from tokenzip.pipeline import CompressionPipeline


@pytest.fixture
def config():
    return TokenZipConfig()


# ── Comment Stripper ─────────────────────────────────────────────

class TestCommentStripper:
    def test_python_single_line_comments(self, config):
        stripper = CommentStripper(config)
        source = '''x = 1  # this is a comment
y = 2  # another comment
z = x + y
'''
        result = stripper.compress(source, "test.py")
        assert "this is a comment" not in result
        assert "another comment" not in result
        assert "x = 1" in result
        assert "z = x + y" in result

    def test_python_preserves_todo(self, config):
        stripper = CommentStripper(config)
        source = '''x = 1  # TODO: fix this later
y = 2  # regular comment
'''
        result = stripper.compress(source, "test.py")
        assert "TODO" in result
        assert "regular comment" not in result

    def test_python_preserves_license(self, config):
        stripper = CommentStripper(config)
        source = '''# Copyright 2024 Acme Inc
# Licensed under MIT
x = 1
'''
        result = stripper.compress(source, "test.py")
        assert "Copyright" in result

    def test_javascript_comments(self, config):
        stripper = CommentStripper(config)
        source = '''// This is a comment
const x = 1; // inline comment
/* Multi-line
   comment */
const y = 2;
'''
        result = stripper.compress(source, "test.js")
        assert "This is a comment" not in result
        assert "inline comment" not in result
        assert "Multi-line" not in result
        assert "const x = 1;" in result
        assert "const y = 2;" in result

    def test_preserves_strings_with_comment_chars(self, config):
        stripper = CommentStripper(config)
        source = '''url = "http://example.com"  # a comment
'''
        result = stripper.compress(source, "test.py")
        assert "http://example.com" in result
        assert "a comment" not in result

    def test_unknown_extension_passthrough(self, config):
        stripper = CommentStripper(config)
        source = "some content # with hash"
        result = stripper.compress(source, "test.xyz")
        assert result == source


# ── Whitespace Normalizer ────────────────────────────────────────

class TestWhitespaceNormalizer:
    def test_collapses_blank_lines(self, config):
        normalizer = WhitespaceNormalizer(config)
        source = "line1\n\n\n\n\nline2"
        result = normalizer.compress(source)
        assert result == "line1\n\nline2"

    def test_strips_trailing_whitespace(self, config):
        normalizer = WhitespaceNormalizer(config)
        source = "line1   \nline2  \t  "
        result = normalizer.compress(source)
        assert result == "line1\nline2"

    def test_preserves_indentation(self, config):
        normalizer = WhitespaceNormalizer(config)
        source = "def foo():\n    x = 1\n        y = 2"
        result = normalizer.compress(source)
        assert "    x = 1" in result
        assert "        y = 2" in result

    def test_collapses_inline_multiple_spaces(self, config):
        normalizer = WhitespaceNormalizer(config)
        source = "x  =   1"
        result = normalizer.compress(source)
        assert result == "x = 1"


# ── RLE Compressor ───────────────────────────────────────────────

class TestRLECompressor:
    def test_compresses_repeated_chars(self, config):
        rle = RLECompressor(config)
        source = "separator = '========================================'"
        result = rle.compress(source)
        assert len(result) < len(source)
        assert '"="*' in result

    def test_ignores_short_runs(self, config):
        rle = RLECompressor(config)
        source = "x = '==='"
        result = rle.compress(source)
        assert result == source

    def test_preserves_alphanumeric_runs(self, config):
        rle = RLECompressor(config)
        source = "aaaaaaaaaa"
        result = rle.compress(source)
        # Should not compress letter runs (they might be meaningful)
        assert result == source


# ── Dictionary Coder ─────────────────────────────────────────────

class TestDictionaryCoder:
    def test_finds_repeated_patterns(self, config):
        config.min_pattern_length = 20
        config.min_pattern_frequency = 2
        coder = DictionaryCoder(config)

        files = {
            "a.py": "result = db.session.query(User).filter_by(id=uid).first()\n" * 3,
            "b.py": "result = db.session.query(User).filter_by(id=uid).first()\n" * 3,
        }
        result = coder.compress_multi(files)
        assert coder.codebook  # codebook should not be empty

        # Compressed output should be shorter
        original_size = sum(len(c) for c in files.values())
        compressed_size = sum(len(c) for c in result.values())
        assert compressed_size < original_size

    def test_generates_codebook_header(self, config):
        config.min_pattern_length = 20
        config.min_pattern_frequency = 2
        coder = DictionaryCoder(config)

        files = {
            "a.py": "result = db.session.query(User).filter_by(id=uid).first()\n" * 3,
            "b.py": "result = db.session.query(User).filter_by(id=uid).first()\n" * 3,
        }
        coder.compress_multi(files)
        header = coder.format_codebook_header()
        assert "[CODEBOOK]" in header
        assert "D1" in header

    def test_no_compression_when_no_patterns(self, config):
        coder = DictionaryCoder(config)
        files = {
            "a.py": "x = 1\n",
            "b.py": "y = 2\n",
        }
        result = coder.compress_multi(files)
        assert result == files


# ── Deduplicator ─────────────────────────────────────────────────

class TestDeduplicator:
    def test_detects_similar_files(self, config):
        config.similarity_threshold = 0.8
        dedup = Deduplicator(config)

        base = """class UserService:
    def __init__(self, db):
        self.db = db

    def get(self, user_id):
        return self.db.query(User).filter_by(id=user_id).first()

    def delete(self, user_id):
        obj = self.db.query(User).filter_by(id=user_id).first()
        self.db.delete(obj)
"""
        variant = base.replace("User", "Order").replace("user_id", "order_id")

        files = {"user_service.py": base, "order_service.py": variant}
        result = dedup.compress_multi(files)

        # The variant should be delta-encoded
        assert "delta from" in result["order_service.py"] or "same as" in result["order_service.py"]

    def test_single_file_no_change(self, config):
        dedup = Deduplicator(config)
        result = dedup.compress("hello world", "test.py")
        assert result == "hello world"


# ── Full Pipeline ────────────────────────────────────────────────

class TestPipeline:
    def test_full_pipeline_compression(self):
        pipeline = CompressionPipeline(TokenZipConfig(
            min_pattern_length=20,
            min_pattern_frequency=2,
        ))

        files = {
            "user_service.py": '''# User service module
# Author: John Doe
# Last modified: 2024-03-15

class UserService:
    """Service for managing users."""

    def __init__(self, db):
        # Initialize with database connection
        self.db = db

    def get_user(self, user_id):
        """Get a user by their ID."""
        user = self.db.session.query(User).filter_by(id=user_id).first()
        if not user:
            raise NotFoundError(f"User {user_id} not found")
        return user.to_dict()

    def delete_user(self, user_id):
        """Delete a user by their ID."""
        user = self.db.session.query(User).filter_by(id=user_id).first()
        if not user:
            raise NotFoundError(f"User {user_id} not found")
        self.db.session.delete(user)
        self.db.session.commit()

    def list_users(self):
        """List all users."""
        users = self.db.session.query(User).all()
        return [u.to_dict() for u in users]
''',
            "order_service.py": '''# Order service module
# Author: Jane Smith
# Last modified: 2024-03-16

class OrderService:
    """Service for managing orders."""

    def __init__(self, db):
        # Initialize with database connection
        self.db = db

    def get_order(self, order_id):
        """Get an order by its ID."""
        order = self.db.session.query(Order).filter_by(id=order_id).first()
        if not order:
            raise NotFoundError(f"Order {order_id} not found")
        return order.to_dict()

    def delete_order(self, order_id):
        """Delete an order by its ID."""
        order = self.db.session.query(Order).filter_by(id=order_id).first()
        if not order:
            raise NotFoundError(f"Order {order_id} not found")
        self.db.session.delete(order)
        self.db.session.commit()

    def list_orders(self):
        """List all orders."""
        orders = self.db.session.query(Order).all()
        return [o.to_dict() for o in orders]
''',
        }

        result = pipeline.compress_files(files)

        # Use pipeline's internal stats (pre-codebook overhead)
        savings_pct = pipeline.stats.char_savings_pct

        print(f"\n{pipeline.stats.summary()}")

        # Should achieve meaningful compression
        assert savings_pct > 20, f"Expected >20% savings, got {savings_pct:.1f}%"

        # All function names should still be present in the output
        all_output = "\n".join(result.values())
        assert "get_user" in all_output or "get_order" in all_output
        assert "UserService" in all_output or "OrderService" in all_output

    def test_skips_target_files(self):
        config = TokenZipConfig(target_files=["main.py"])
        pipeline = CompressionPipeline(config)

        files = {
            "main.py": "# This comment should NOT be stripped\nx = 1\n",
            "utils.py": "# This comment SHOULD be stripped\ny = 2\n",
        }

        result = pipeline.compress_files(files)
        assert "should NOT be stripped" in result["main.py"]

    def test_stats_tracking(self):
        pipeline = CompressionPipeline()
        files = {
            "test.py": "# comment\n" * 10 + "x = 1\n",
        }
        pipeline.compress_files(files)

        assert pipeline.stats.original_chars > 0
        assert pipeline.stats.compressed_chars < pipeline.stats.original_chars
        assert pipeline.stats.char_savings_pct > 0
