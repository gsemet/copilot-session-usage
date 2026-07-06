# Reference

An external source document — scientific papers, API specifications, lookup tables, or authoritative references — mirrored or linked within the knowledge base.
Use Reference when bringing external information into the knowledge base for easy agent access. Do NOT use Reference for your own observations (use Finding), interpretations (use Concept), or workflows (use Playbook). Personal notes on a paper belong in a Finding or Concept, not in Reference.
Immutable. References mirror or link to external sources. If the upstream changes, create a new Reference with updated `schema_version` rather than editing the old one.
Belongs to the Lookup layer. Referenced by Concepts, Structures, Principles, and Findings for authoritative backing.

- [Debug Log JSONL Format](debug-log-format.md) — Structure of Copilot debug log events, with focus on fields relevant to cost extraction.  [Reference]
- [Pricing Data Formats](pricing-formats.md) — Schema and format documentation for models-and-pricing.yml, custom-models-pricing.yml, and the internal pricing dict.  [Reference]
