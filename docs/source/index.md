# copilot-session-usage

[![GitHub](https://img.shields.io/badge/GitHub-copilot--session--usage-181717?logo=github)](https://github.com/gsemet/copilot-session-usage)

**copilot-session-usage** reads VS Code Copilot debug logs and tells you
how much each AI coding session cost in USD.

VS Code does not show session costs in its UI. The debug logs contain
token counts per model. This tool reads those logs, applies the real
published pricing (with cache discounts and long-context tiers), and
prints a cost report in seconds.

The most common use: after a heavy agentic session, run
`copilot-session-usage latest` to see what it cost.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} 📦 Installation
:link: installation
:link-type: doc

Install `copilot-session-usage` with uv or pip.
:::

:::{grid-item-card} 🚀 Getting Started
:link: tutorials/getting-started
:link-type: doc

Analyze your first session and understand the output in under 5 minutes.
:::

:::{grid-item-card} 📖 How-To Guides
:link: how-to/index
:link-type: doc

Export to JSON, track spending over time, integrate in scripts,
and configure WSL2.
:::

:::{grid-item-card} 📚 Reference
:link: reference/index
:link-type: doc

Complete CLI and Python API documentation.
:::

:::{grid-item-card} 💡 How It Works
:link: explanation/how-cost-estimation-works
:link-type: doc

Where the logs live, how tokens are counted,
and how pricing tiers are applied.
:::

::::

```{toctree}
:maxdepth: 2
:hidden:

Installation <installation>
Tutorials <tutorials/index>
How-To <how-to/index>
Reference <reference/index>
How It Works <explanation/index>
Changelog <changelog>
```
