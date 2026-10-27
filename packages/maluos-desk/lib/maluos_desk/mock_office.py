"""The mock Business OS office moved to maluos-estate (Phase 13 slice 1) so a server image can run it too;
`python3 -m maluos_desk.mock_office` still works and means the same thing."""
import sys
sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate.mock_office import *          # noqa: F401,F403
from maluos_estate.mock_office import main

if __name__ == "__main__":
    sys.exit(main())
