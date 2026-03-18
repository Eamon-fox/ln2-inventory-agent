# Schema Context

Schema context is the minimum shared description of how LN2 inventory data is structured.

## Include These Concepts

- active dataset path
- box layout contract
- effective field list
- per-box field overrides
- field aliases
- structural field set
- mutation and validation expectations

## Source of Truth

- Effective fields come from current dataset metadata.
- Structural fields remain fixed unless the application architecture changes.
- Validation rules are stricter than prompt guidance; when in doubt, validation wins.
