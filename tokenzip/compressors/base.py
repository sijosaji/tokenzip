from abc import ABC, abstractmethod

from tokenzip.config import TokenZipConfig


class BaseCompressor(ABC):
    """Base class for all compressors in the pipeline."""

    def __init__(self, config: TokenZipConfig):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this compression stage."""
        ...

    @abstractmethod
    def compress(self, content: str, filename: str = "") -> str:
        """Compress a single file's content.

        Args:
            content: The text content to compress.
            filename: Optional filename for language detection.

        Returns:
            Compressed text content.
        """
        ...

    def compress_multi(self, files: dict[str, str]) -> dict[str, str]:
        """Compress multiple files. Override for cross-file compressors.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Mapping of filename -> compressed content.
        """
        return {fn: self.compress(content, fn) for fn, content in files.items()}
