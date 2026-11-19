"""Model registry.

Importing this package imports every ORM model, which registers every table on
``Base.metadata``. Alembic imports it for exactly that reason; a model that is
not imported here does not exist as far as migrations are concerned.
"""
