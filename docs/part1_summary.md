# Part 1 Summary: MCP and the Fetch Server

*Article: Ksenia Se, "What Is MCP, and Why Is Everyone Suddenly Talking About It?" (Hugging Face, 2025). Server explored: the official Fetch MCP server (source code read).*

## Key MCP concepts

Language models are powerful but isolated from the data and systems where useful context lives. Before MCP, each application needed custom code for each data source, an N×M integration problem that made agents brittle. The Model Context Protocol, released by Anthropic in November 2024, is one open standard: every application and every tool implements it once, turning N×M into N+M.

MCP has three roles. The **Host** is the AI application the user interacts with, such as Claude Desktop, an IDE or an Agents SDK program. The host creates one **Client** per server, and each client keeps a one-to-one connection with a **Server**. The server wraps a tool or data source and exposes primitives: **tools** the model calls, **resources** the application reads as context, and **prompts**. Capabilities are discovered at runtime, so the host needs no hard-coded integration. The article frames MCP as the agent's integration layer, not its reasoning engine, and lists open problems: operational overhead, immature security, and tools that are only as good as their descriptions.

## Critique of the Fetch server

Fetch exposes one tool, `fetch(url, max_length, start_index, raw)`, plus a prompt. Judged by the three design principles from class:

- **Well-defined interface: strong.** Arguments are typed and bounded, and the tool is annotated as read-only.
- **Predictable behavior: mostly strong.** A robots.txt refusal, an HTTP error or a private address returns a clear error, and `start_index` pagination bounds output size. However, the output is one unstructured string, with continuation hints written inside the text.
- **Isolated, single-purpose functionality: weak.** One tool retrieves the page, enforces robots.txt, converts HTML to Markdown, and truncates. The `raw` flag switching behaviour is a sign of "fetch *and* convert".

The bundling is defensible, because splitting conversion into a second tool would push large raw HTML through the model's context. Still, it shows why single-purpose tools are preferred: they are easier for the model to choose, test and recombine. My toolkit follows that rule and combines tools only in an explicit orchestration tool.
