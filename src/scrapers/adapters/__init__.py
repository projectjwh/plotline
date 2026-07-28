"""Platform acquisition adapters.

Importing this package registers every adapter into
``src.scrapers.adapters.base.ADAPTERS`` (keyed by ``source``). Use
``get_adapter(source)`` to route a Bronze file to its parser.
"""
from src.scrapers.adapters.base import ADAPTERS, BaseAdapter, detect_block, get_adapter, register

# Import modules for their @register side effects.
from src.scrapers.adapters import webtoon    # noqa: E402,F401
from src.scrapers.adapters import listings   # noqa: E402,F401
from src.scrapers.adapters import royalroad  # noqa: E402,F401
from src.scrapers.adapters import lezhin     # noqa: E402,F401
from src.scrapers.adapters import joara      # noqa: E402,F401

__all__ = ["ADAPTERS", "BaseAdapter", "detect_block", "get_adapter", "register"]
