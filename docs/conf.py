"""Sphinx configuration for the Plotline documentation.

Build locally:  sphinx-build -b html docs docs/_build/html -W --keep-going
"""
from __future__ import annotations

# -- Project information -----------------------------------------------------
project = "Plotline"
author = "Junwoo Hyung"
copyright = "2026, Junwoo Hyung"
release = "1.0"
version = "1.0"

# -- General configuration ---------------------------------------------------
extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
    "sphinx.ext.intersphinx",
]

# MyST (Markdown) options
myst_enable_extensions = ["colon_fence", "deflist", "tasklist", "substitution"]
myst_heading_anchors = 3
# Let plain ```mermaid fences render as diagrams (and render natively in Artifacts).
myst_fence_as_directive = ["mermaid"]

source_suffix = {".md": "markdown"}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- HTML output -------------------------------------------------------------
html_theme = "furo"
html_title = "Plotline"
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
}

# -- intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
