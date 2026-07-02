---
type: Structure
title: Knowledge Base Information Types
description: The seven OKF information types used in this bundle and how they 
  relate.
tags: [meta, okf, information-mapping, taxonomy]
timestamp: 2026-07-02T00:00:00Z
subject: knowledge/ OKF bundle
parts: [Concept, Structure, Principle, Playbook, Reference, Finding, Experiment]
---

# Knowledge Base Information Types

This bundle organizes knowledge with seven information types, close to
Information Mapping / DITA. Each maps to a schema in `_schema/` and a folder.

| Type | Answers | Nature | Folder |
|------|---------|--------|--------|
| **Concept** | "What is this idea?" | Explanatory, stable | `concepts/` |
| **Structure** | "How is this object composed / how does it work?" | Descriptive, stable | `structures/` |
| **Principle** | "What standard/convention do we follow?" | Normative, agreed with humans | `principles/` |
| **Playbook** | "How do I perform this task?" | Procedural | `guides/` |
| **Reference** | "What are the exact values/fields?" | Lookup, stable | `reference/` |
| **Finding** | "What did we observe at time T?" | Empirical, dated, falsifiable | `findings/` |
| **Experiment** | "How do we test claim X?" | Reusable procedure to run 1–2 times | `experiments/` |

## Empirical vs stable knowledge

- **Findings** and **Experiments** are the *empirical* layer: dated, testable,
  and possibly wrong. A Finding records what someone truthfully believed at a
  moment; an Experiment is a template that, when run, produces Findings.
- **Concept / Structure / Principle / Playbook / Reference** are the *stable*
  layer. They are refined deliberately (Principles with humans) and are
  promoted from converged Findings, not dumped ad hoc.

## Lifecycle

Agents dump Findings freely. The `consolidate-knowledge-base` skill later
detects contradictions, schedules Experiments, and proposes promotions into the
stable layer under human confirmation.
