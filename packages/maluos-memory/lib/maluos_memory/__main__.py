"""python3 -m maluos_memory: the memory face daemon (maluos-memory.service)."""
import sys

from .server import serve

if __name__ == "__main__":
    sys.exit(serve(sys.argv[1:]))
