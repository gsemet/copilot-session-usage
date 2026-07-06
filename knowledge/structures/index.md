# Structure

A description of how an object, system, or artifact is composed and how its parts relate — the "how it works" view.
Use Structure when documenting system architecture, component relationships, or mechanical composition. Do NOT use Structure for abstract ideas (use Concept), operational procedures (use Playbook), or human-agreed standards (use Principle).
Mutable. Updated as the system evolves. Like Concepts, Structures are never deleted; obsolete Structures are marked `status: deprecated` and linked to replacements.
Belongs to the Semantic layer. Promoted from confirmed Hypotheses or converged Findings. Cross-cuts multiple Concepts.

- [Cache Cost Approximation](cache-cost-approximation.md) — How copilot-session-usage approximates Anthropic cache-write costs when VS Code debug logs do not expose cache_creation token counts.  [Structure]
- [Knowledge Base Information Types](knowledge-base-information-types.md) — The seven OKF information types used in this bundle and how they relate.  [Structure]
- [Session Discovery Algorithm](session-discovery-algorithm.md) — How a coding agent finds the correct session directory when the user only knows the title, date, or workspace from the Agent Debug Panel.  [Structure]
- [Subagent Cost Tracking](subagent-cost-tracking.md) — How subagent costs are logged, aggregated, and correlated with parent sessions.  [Structure]
- [VS Code Copilot Extension Debug Logs](vscode-copilot-extension.md) — How the VS Code Copilot extension stores session logs and what agents need to know about path resolution.  [Structure]
