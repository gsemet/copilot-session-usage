# Experiment

A reusable, prepared procedure designed to test a Hypothesis and produce empirical Findings. Each execution yields one or more Finding documents.
Use Experiment when you need a reproducible test procedure. Do NOT use Experiment for ad-hoc observations (write a Finding directly) or for operational workflows (use Playbook).
The Experiment template itself is mutable while in `proposed` or `active` status. Once `retired` or `superseded`, it should not be modified. Outcomes are recorded as separate Finding documents, not by editing the Experiment.
Belongs to the Testing layer. Tests Hypotheses. Produces Findings. May be superseded by improved experimental designs.

- [Verify Subagent Cost Attribution](verify-subagent-cost-attribution.md) — Check that subagent token costs are attributed to their runSubagent call and not double-counted in the parent session total.  [Experiment]
