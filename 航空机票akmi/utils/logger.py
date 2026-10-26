from __future__ import annotations

import sys

try:
    from loguru import logger
except ImportError:
    class PrintLogger:
        @staticmethod
        def info(message, *args):
            if args:
                message = message.format(*args)
            out = getattr(sys.stdout, "buffer", None)
            if out:
                out.write((str(message) + "\n").encode("utf-8", errors="replace"))
                out.flush()
            else:
                print(message)

    logger = PrintLogger()
