# concepts

- [Copilot CLI Differences](copilot-cli.md) — How session cost tracking differs when using copilot-cli instead of the VS Code extension.  [Concept]
- [Cost Optimization Patterns](cost-optimization.md) — Common patterns that inflate session costs and strategies to reduce them.  [Playbook]
- [Session Cost Analysis](session-cost-analysis.md) — Process of extracting token usage metrics from Copilot debug logs and estimating monetary cost based on per-model pricing.  [Concept]
- [Session Cost Tracking Overview](overview.md) — How VS Code Copilot tracks and exposes per-session token costs for coding agents.  [Concept]
- [Session Discovery Algorithm](session-discovery-algorithm.md) — How an agent resolves a session title, date, or workspace to its debug-log directory via `state.vscdb`.  [Concept]
- [Subagent Cost Tracking](subagent-cost-tracking.md) — How subagent costs are logged, aggregated, and correlated with parent sessions.  [Concept]
- [Threshold-Based Pricing](threshold-based-pricing.md) — How multi-tier model pricing (e.g. GPT-5.4 ≤272K vs >272K) is parsed from YAML and applied during cost estimation.  [Concept]
- [VS Code Copilot Extension Debug Logs](vscode-copilot-extension.md) — How the VS Code Copilot extension stores session logs and what agents need to know about path resolution.  [Concept]
