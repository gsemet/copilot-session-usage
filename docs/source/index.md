# copilot-session-usage

[![GitHub](https://img.shields.io/badge/GitHub-copilot--session--usage-181717?logo=github)](https://github.com/gsemet/copilot-session-usage)

**copilot-session-usage** reads local VS Code Copilot debug logs and/or local
Copilot CLI/Copilot App session logs and tells you how much each AI coding
session cost in USD.

Neither VS Code nor Copilot CLI/Copilot App show session costs in their UI.
Their local logs contain token counts per model. This tool reads those logs,
applies the real published pricing (with cache discounts and long-context
tiers), and prints a cost report in seconds — all from files already on your
machine, with no network access required.

The most common use: after a heavy agentic session, run
`copilot-session-usage latest` (or `copilot-session-usage --agent cli latest`
for Copilot CLI/App sessions) to see what it cost.

Links to source code: [gsemet/copilot-session-usage](https://github.com/gsemet/copilot-session-usage)

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

Export to JSON, analyze Copilot CLI/App sessions, track spending over time,
integrate in scripts, and configure WSL2.
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
