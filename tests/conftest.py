import os
import sys
from pathlib import Path

os.environ["BOT_OPS_DEMO"] = "1"  # before bot_ops.config is imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
