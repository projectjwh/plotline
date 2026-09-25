"""Plotline application backend (Phase 2): the IMDb + DCInside platform for story IP.

The layout is modular. Every domain package owns its tables (``repo.py``), exposes a
service (``service.py``) and a thin HTTP layer (``router.py``). Replaceable behaviour
sits behind a Protocol plus a named registry and is selected in ``config/policy/app.yaml``.
Blueprint: ``docs/product/architecture.md``.

Run:   uvicorn --factory src.app.main:create_app --reload
Tests: pytest -q tests/app
"""
