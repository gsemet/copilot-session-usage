# Record Finding

`record-finding` is a handoff tool for investigations that outgrow the current
model. When a small model struggles to reach a reliable conclusion, it can leave
the maximum useful evidence for a bigger model to continue from.

## Why use this skill?

Debugging sessions and log investigations often reach a useful boundary before
they reach a reliable conclusion. A small model may have already found the
relevant files, tested several explanations, and identified what remains unclear,
but lack the context window or reasoning capacity to finish. If that partial work
stays in the conversation, a bigger model has to rediscover it.

Usage:

```md
/record-findings
```

## Use it when

- a small or fast model is stuck after a meaningful investigation;
- you need to hand off debugging context to a bigger model without starting over;
- you have finished diagnosing a bug or unexpected behavior;
- you verified how VS Code, Copilot, pricing, or session logs behave; or
- you discovered a non-trivial fact that another investigation may need.

The skill writes exactly one immutable file under `knowledge/findings/` and runs
the knowledge-base validation checks.

## Do not use it for

- team standards or rules, which belong in a Principle;
- descriptions of how a system or object is composed, which belong in a Structure;
- stable, consolidated ideas, which belong in a Concept; or
- a collection of unrelated observations.

Record one claim at a time. If a conclusion changes later, add a new Finding that
links to the earlier one instead of rewriting the historical record.

## Example prompts

- "I am stuck on why this Copilot session has no model name. Record everything a
  bigger model needs to continue."
- "Create a Finding from the investigation of the pricing mismatch."
- "Save the parser behavior, attempted fixes, and open questions as an OKF
  Finding for a bigger model."
