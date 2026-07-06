# Playbook

A reproducible, step-by-step workflow or procedure that produces a specific result given the current understanding of the system.
Use Playbook when documenting "how to do X" — deployment steps, debugging procedures, setup guides. Do NOT use Playbook for one-off observations (use Finding), system architecture (use Structure), or planned deliverables (use Outcome).
Mutable while active. When a better workflow is found, the old Playbook is marked `status: deprecated` or `superseded` with `superseded_by` pointing to the replacement. Playbooks are experienced until proven false or obsolete.
Belongs to the Operational layer. References Concepts and Structures for context. May be referenced by Outcomes as execution paths.

- [Automation Scripts for Cost Extraction](automation-scripts.md) — Reference Python patterns for extracting and aggregating session costs from Copilot debug logs.  [Playbook]
- [Cost Optimization Patterns](cost-optimization.md) — Common patterns that inflate session costs and strategies to reduce them.  [Playbook]
- [WSL2 Setup Guide](wsl2-setup.md) — Configure copilot-session-usage when running VS Code on Windows with WSL2, including path resolution and troubleshooting.  [Playbook]
