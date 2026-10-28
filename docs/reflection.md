# Reflection

I drew the lines between the three tools by asking what each one is allowed to touch.

- `check_coop_item` (Data) may only read the coop website. It answers one question: "does the coop sell this item in this size, and at what price?"
- `record_ledger_entry` (Action) may only write to the troupe's ledger. It records a single charge or payment and never contacts the coop.
- `process_member_order` (Orchestration) owns the business rule that connects them. It checks the item first, charges the member only if the item and size actually exist, and records any cash handed over on the spot.

The hardest boundary was payments. My first instinct was separate `record_order` and `record_payment` tools, which would have broken the three-tool limit. Modelling both as entries in one append-only ledger kept the Action tool single-purpose ("write one entry") and handled both late payers and members who pay in advance, through a negative balance (credit). Read-only views such as balances, a member's statement and the consolidated coop order are pure lookups, so I exposed them as MCP resources, not extra tools. The host injects them as fresh context on every model call.

Three tools felt right for the core loop a chef repeats every week: check, order, collect. The limit also forced cleaner designs. Real use, though, already pushes past three:

- adding or removing members (I edit the roster file by hand for now)
- marking items as received from the coop, so they leave the pending order
- bulk orders for the whole troupe

Matching items was also harder than expected. The catalog is in French, so the model has to translate requests like "khaki troop shirt" before searching. Ambiguous or size-less requests had to return structured `ambiguous` and `needs_variant` answers so the agent asks instead of guessing. On the infrastructure side, my antivirus intercepts HTTPS, which broke package installs and certificate checks. Using the operating system's certificate store (truststore) fixed this without disabling verification.

Next steps:

- the member and delivery tools above
- reminder messages to members who owe money, sent only after the chef confirms
- caching the full catalog for offline use at camp
- supporting several units at the group level

I deliberately left out submitting orders to the coop's website. That is an outward-facing action that should stay a human decision.
