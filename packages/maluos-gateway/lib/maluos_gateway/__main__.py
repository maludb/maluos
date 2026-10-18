import asyncio, sys
from .server import main
asyncio.run(main(sys.argv[1:]))
