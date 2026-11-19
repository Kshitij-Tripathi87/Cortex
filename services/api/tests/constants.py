"""Fixed values shared by the tests. Nothing here depends on the machine clock."""

from datetime import date
from uuid import UUID

DEV_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")

# Reference date of the demo dataset (NEXUS_DEMO_AS_OF).
DEMO_AS_OF = date(2026, 11, 19)
