"""Start the MCP server from any working directory: python /path/to/run_server.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_ops.server import main  # noqa: E402

main()
