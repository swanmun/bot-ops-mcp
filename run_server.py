"""Start the MCP server from any working directory: python /path/to/run_server.py

[한국어] 어느 작업 폴더에서 실행하든 MCP 서버를 띄운다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_ops.server import main  # noqa: E402

main()
