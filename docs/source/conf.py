"""Sphinx configuration for copilot-session-usage."""

from __future__ import annotations

import importlib.metadata

project = "copilot-session-usage"
author = "Ampere SDV Team"
version = importlib.metadata.version("copilot-session-usage")
release = version

copyright = "2026, Ampere SDV Team"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_click",
    "sphinx_autodoc_typehints",
    "sphinx_design",
    "sphinx_copybutton",
]

myst_enable_extensions = ["colon_fence", "deflist"]

html_theme = "furo"
html_title = f"copilot-session-usage {version}"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_js_files = ["changelog.js"]

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
