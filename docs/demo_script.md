# Screencast script (target: about 6 minutes)

**Before recording:**
- Run `python scripts/reset_demo.py`.
- Open two terminals: one for `python agent.py`, one to show `data/ledger.json`.
- Open VS Code on `troupe_coop/server.py`.
- Increase the terminal font size.

---

## 1. Intro: who I am and the problem (0:00 to 0:50)

> "Hi, I'm Christophe. Besides being a student, I'm a scout chef. I lead a troupe in Scouts du Liban, and this project comes from a problem I actually have right now.
> Every few weeks my scouts need things from the SDL coop: a uniform shirt, a beret, a scarf ring. I collect the requests and check whether the coop has the item in the right size, and how much it costs. Then I have to remember who paid me in advance, who paid half, and who still owes me money. Right now that's all in WhatsApp messages and in my head.
> So for this assignment I built an MCP toolkit and an agent that does it for me."

## 2. The three tools and the architecture (0:50 to 2:00)

Show the README architecture diagram, then `server.py`.

> "The agent is the **MCP host**. It's built with the OpenAI Agents SDK, and it contains an **MCP client** that starts my **FastMCP server** over stdio. The server has exactly three tools:"

- **Data tool: `check_coop_item`.** "It reads the live coop website, which is an Odoo shop, and returns the price and the sizes that exist. It never changes anything."
- **Action tool: `record_ledger_entry`.** "It writes one charge or one payment to a member's account and returns the new balance. Positive means they owe me; negative means they paid in advance."
- **Orchestration tool: `process_member_order`.** "It calls the data tool first. Only if the item and size exist does it call the action tool to charge the member, and then it records any cash they gave me on the spot."

> "Balances and the consolidated coop order aren't tools. They're read-only **MCP resources**, which the host reads and gives to the model as context."

Run `python agent.py --check` to show the 3 tools and 4 resources being discovered over MCP.

## 3. Live demo (2:00 to 4:45)

Run `python agent.py`. Point at the cyan **-> agent calls MCP tool** lines, the yellow **<- server returned** lines, and the `[MCP server]` log lines. That's the full round trip.

Type these one at a time:

1. `Jad needs a khaki troupe shirt in size 8, he gave me 10 dollars`
   - Expected: the agent translates the item to *Chemise Troupe Kaki* and calls `process_member_order`. The coop doesn't make that shirt in size 8, so it returns not_recorded, suggests size 10, and nothing is recorded.
   - Say: *"This is a real catalog gap. The kaki shirt starts at size 10."*
2. `ok size 10 then`
   - Expected: the order is recorded with the $10 payment. Jad already owed $15, so the reply should show the new balance.
3. `Maya wants a beret size 59 and a bague foulard`
   - Expected: two orders, both paid from Maya's $20 advance, leaving her with credit.
4. `Combien coûte la chemise troupe ?`
   - Expected: the agent answers in French and asks whether you mean *Bleue* or *Kaki* (the `ambiguous` status).
5. `Ziad paid me 5$`
   - Expected: a clear error that Ziad isn't in the roster, with the member list (failure case).
6. `Karim gave me 20 dollars in advance`
   - Expected: `record_ledger_entry`, payment type. Karim now has $20 credit.
7. `Who still owes me money?` then `What do I need to buy from the coop?`
   - Expected: answers come from the resources: balances, and the order grouped by item and size.

Switch to the second terminal and open `data/ledger.json` to show the entries that were just written.

## 4. Tests and failure handling (4:45 to 5:30)

Run `pytest` (35 passing). Mention the tested failures:
- size not offered
- discontinued variant
- item not found
- coop site down
- unknown member
- negative amount
- "an unavailable size records nothing"

## 5. Challenges and how I solved them (5:30 to 6:30)

- **Keeping tools single-purpose under a three-tool limit.** "My first design had separate order and payment tools. I merged them into one ledger entry, a charge or a payment, which also handles paying in advance as credit. Read-only views became resources."
- **Predictable failures.** "The data tool returns structured statuses (`unavailable`, `needs_variant`, `ambiguous`) with suggestions, so the agent asks me instead of guessing a size."
- **French catalog.** "Item names are in French, so the agent translates before searching and keeps the official name in its answer."
- **My antivirus intercepting HTTPS.** "It broke pip and certificate checks. I used the OS certificate store through truststore and uv, without ever disabling TLS verification."

> "The code is on GitHub at [link]. Next steps: managing members, marking items as received from the coop, and reminders for members who owe money. Thanks!"
