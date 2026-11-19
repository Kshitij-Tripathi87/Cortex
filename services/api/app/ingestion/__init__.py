"""Pure ingestion modules: reading, mapping, normalizing and validating source rows.

Nothing in this package touches the database or HTTP. Orchestration and all
writes live in app/services/ingestion_service.py.
"""
