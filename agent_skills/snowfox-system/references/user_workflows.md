# GUI And Operator Paths

Use this reference when the user asks "where do I click", "how do I enable X", or when the Agent should hand work back to the human user.

## Main Settings Entry

- The main window toolbar gear button opens Settings.

## Settings > Data

Use this section for:

- switching the active dataset
- renaming a dataset
- deleting a dataset
- changing the data root

If the user wants to change which managed inventory is open, point them here.

## Settings > AI

Use this section for:

- changing provider
- changing model
- changing max steps
- toggling thinking
- editing custom prompt

The custom prompt is style guidance only. It does not override tool-safety or workflow policy.

## Settings > Local API

Use this section for:

- enabling or disabling the local open API
- changing the port
- copying the external skill template

Important boundary:

- This API is loopback-only.
- It is disabled by default.
- It follows the current GUI session and current dataset.
- It is read-only plus GUI handoff only, not a write API.

## Settings > Manage Fields

If the user wants to add, remove, rename, reorder, or change custom field definitions, direct them here.

The Agent must not pretend it can perform field management itself.

## Box/Layout Management

- Box/layout changes are a managed workflow.
- The entry is `Settings > Data > Manage Boxes`.
- `manage_boxes` requires human confirmation.
- This dialog supports four operations: add boxes, remove box, set box tag, and set position indexing.
- If the user asks to switch between numeric and alphanumeric positions, direct them to `Settings > Data > Manage Boxes > Set position indexing`.
- Explain that this changes display/input mode only; stored inventory positions remain integers.
- If the user asks to change box structure, explain the Settings / box-management path and the confirmation requirement.

## Plan Execution

- Inventory mutation tools like `add_entry`, `edit_entry`, `move`, `takeout`, and `rollback` stage intent only.
- The human user executes staged operations from the GUI.

If the user thinks the Agent can directly commit those writes on its own, correct that assumption.

## Migration

- Migration works inside `migrate/`.
- The Agent can help convert staged inputs and validate output.
- Final import still requires explicit human confirmation and a target dataset name.
