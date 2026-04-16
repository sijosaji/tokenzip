"""CLI interface for TokenZip."""

import argparse
import sys

from tokenzip.config import TokenZipConfig
from tokenzip.pipeline import CompressionPipeline, load_files


def main():
    parser = argparse.ArgumentParser(
        prog="tokenzip",
        description="TokenZip — Text-domain compression for LLM prompts. "
        "Reduce token usage by 35-45%% without losing context.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # compress command
    compress_parser = subparsers.add_parser(
        "compress", help="Compress files and output the result"
    )
    compress_parser.add_argument(
        "path", help="File or directory to compress"
    )
    compress_parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Files to skip (files being edited). Can be specified multiple times.",
    )
    compress_parser.add_argument(
        "--no-codebook",
        action="store_true",
        help="Don't include the codebook header in output",
    )
    compress_parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Skip comment stripping stage",
    )
    compress_parser.add_argument(
        "--stats",
        action="store_true",
        help="Print compression stats to stderr",
    )
    compress_parser.add_argument(
        "--output", "-o",
        help="Output file (default: stdout)",
    )
    compress_parser.add_argument(
        "--min-pattern-length",
        type=int,
        default=30,
        help="Minimum pattern length for dictionary coding (default: 30)",
    )
    compress_parser.add_argument(
        "--min-pattern-freq",
        type=int,
        default=3,
        help="Minimum pattern frequency for dictionary coding (default: 3)",
    )

    # stats command
    stats_parser = subparsers.add_parser(
        "stats", help="Show compression statistics without outputting compressed content"
    )
    stats_parser.add_argument(
        "path", help="File or directory to analyze"
    )
    stats_parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Files to skip",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "compress":
        _do_compress(args)
    elif args.command == "stats":
        _do_stats(args)


def _do_compress(args):
    """Execute the compress command."""
    config = TokenZipConfig(
        target_files=args.target,
        include_codebook=not args.no_codebook,
        min_pattern_length=args.min_pattern_length,
        min_pattern_frequency=args.min_pattern_freq,
    )

    files = load_files(args.path, args.target)

    if not files:
        print(f"No supported files found in: {args.path}", file=sys.stderr)
        sys.exit(1)

    pipeline = CompressionPipeline(config)
    compressed = pipeline.compress_files(files)

    # Build output
    output_parts = []
    for fn, content in sorted(compressed.items()):
        if len(compressed) > 1:
            output_parts.append(f"--- {fn} ---")
        output_parts.append(content)

    output = "\n".join(output_parts)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Compressed output written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    if args.stats:
        print("\n" + pipeline.stats.summary(), file=sys.stderr)


def _do_stats(args):
    """Execute the stats command."""
    config = TokenZipConfig(target_files=args.target)

    files = load_files(args.path, args.target)

    if not files:
        print(f"No supported files found in: {args.path}", file=sys.stderr)
        sys.exit(1)

    pipeline = CompressionPipeline(config)
    pipeline.compress_files(files)

    print(pipeline.stats.summary())

    # Per-file breakdown
    print(f"\nFiles processed: {len(files)}")
    for fn, content in sorted(files.items()):
        print(f"  {fn}: {len(content):,} chars")


if __name__ == "__main__":
    main()
