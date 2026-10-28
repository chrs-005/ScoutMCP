# Screencast script (target: 5:00 to 5:30; the assignment requires 5 to 7 minutes)

**Before recording:**
- In the project folder, run `.venv\Scripts\activate`, then `python scripts/reset_demo.py`.
- Have `python agent.py` ready in one terminal and VS Code open on `troupe_coop/server.py`.
- Increase the terminal font size.

---

## 1. Intro (0:00 to 0:40)

> "Hi, I'm Christophe. I'm a scout chef in Scouts du Liban, and this project solves a problem I have right now. My scouts order uniform pieces from the SDL coop. I have to check whether the coop has each item in the right size and at what price, then remember who paid in advance and who still owes me. So I built an MCP toolkit and an agent that does it for me."

## 2. The three tools (0:40 to 1:40)

Show `server.py` while talking.

> "The agent is the **MCP host**, built with the OpenAI Agents SDK. Its **MCP client** connects to my **FastMCP server** over stdio. The server has exactly three tools:
> - The **Data tool**, `check_coop_item`, reads the live coop website and returns the price and the sizes that exist. It changes nothing.
> - The **Action tool**, `record_ledger_entry`, writes one charge or payment to a member's account.
> - The **Orchestration tool**, `process_member_order`, calls the data tool first. Only if the item exists does it call the action tool to charge the member and record what they paid.
> Balances and the coop order list are read-only **MCP resources**, not tools."

## 3. Live demo (1:40 to 4:00)

Run `python agent.py`.

> "The `->` lines are the agent calling a tool through the MCP client, `[MCP server]` is my server working, and `<-` is the result coming back. That's the full round trip."

Type:
1. `How much is the chemise troupe?`
   - "There are two troupe shirts, so the data tool says 'ambiguous' and the agent asks me which one: Bleue or Kaki."
2. `Jad needs a khaki troupe shirt in size 8, he gave me 10 dollars`
   - "Size 8 doesn't exist for this shirt. The tool suggests 10, and nothing was recorded."
3. `ok size 10 then`
   - "Now the orchestration checked, then charged, then recorded the payment. Jad owes $20."
4. `Ziad paid me 5$`
   - "Failure case: Ziad isn't in the troupe, so I get a clear error, not a silent failure."
5. `Who still owes me money?`

## 4. Challenges (4:00 to 5:00)

> "Three challenges:
> 1. **Keeping tools single-purpose with only three.** I merged orders and payments into one ledger entry, a charge or a payment, which also handles paying in advance. Read-only views became resources instead of extra tools.
> 2. **Predictable failures.** The data tool returns clear statuses like 'unavailable' or 'ambiguous', with suggestions, so the agent asks me instead of guessing. My 35 tests cover every failure case.
> 3. **A bug only the live agent showed.** The model sent sizes as 'Size: 10' instead of '10', so valid sizes were refused. I fixed it and added that case as a test."

## 5. Close (5:00 to 5:15)

> "The code is on GitHub at github.com/chrs-005/ScoutMCP. Next steps: managing members and payment reminders. Thanks!"
