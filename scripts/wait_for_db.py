"""Wait until PostgreSQL accepts connections and answers a query.

Usage (from services/api):
    uv run python ../../scripts/wait_for_db.py            # DATABASE_URL
    uv run python ../../scripts/wait_for_db.py --test     # TEST_DATABASE_URL

Exits 0 as soon as the database answers, 1 when the timeout passes. The
database password is never printed.
"""

import argparse
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="database URL; default: DATABASE_URL from the settings")
    parser.add_argument(
        "--test", action="store_true", help="wait for TEST_DATABASE_URL instead of DATABASE_URL"
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait (default 60)")
    arguments = parser.parse_args()

    if arguments.url:
        url = arguments.url
    else:
        settings = get_settings()
        url = settings.test_database_url if arguments.test else settings.database_url
        if not url:
            print("TEST_DATABASE_URL is not configured.", file=sys.stderr)
            return 1

    shown = make_url(url).render_as_string(hide_password=True)
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    deadline = time.monotonic() + arguments.timeout
    last_error = "no attempt made"
    try:
        while True:
            try:
                with engine.connect() as connection:
                    version = connection.execute(text("SHOW server_version")).scalar_one()
                print(f"PostgreSQL {version} is ready at {shown}")
                return 0
            except SQLAlchemyError as exc:
                last_error = type(exc).__name__
            if time.monotonic() >= deadline:
                break
            time.sleep(1.0)
    finally:
        engine.dispose()

    print(
        f"PostgreSQL at {shown} did not become ready within {arguments.timeout:.0f}s "
        f"(last error: {last_error}).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
