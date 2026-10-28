# Part 1: MCP Concepts and a Critique of the Fetch Server

**Source:** Ksenia Se, "What Is MCP, and Why Is Everyone – Suddenly! – Talking About It?" (Hugging Face / Turing Post, March 2025). **Server explored:** the official Fetch MCP server (`modelcontextprotocol/servers/src/fetch`).

## Key MCP concepts

The article starts from a simple observation: language models are capable in isolation but cut off from the data and systems where useful context lives. Before MCP, every application wired up each data source with custom code, an N×M integration problem that made agents brittle. The Model Context Protocol, released by Anthropic in November 2024, replaces this with one open standard. Each application and each tool implements MCP once, turning N×M into N+M.

The architecture has three roles. The **Host** is the AI application the user interacts with, such as Claude Desktop, an IDE, or in my project an OpenAI Agents SDK program. Inside the host, each **Client** keeps a one-to-one connection with a **Server**. A server wraps a tool or data source and exposes three primitives:

- **Tools:** actions the model decides to call.
- **Resources:** read-only data the application attaches as context.
- **Prompts:** reusable templates.

Capabilities are discovered at runtime, so the host needs no hard-coded integration. The article positions MCP as the agent's integration layer, not its reasoning engine, and flags open problems: operational overhead, immature security, and tools that are only as useful as their descriptions.

## The Fetch server

Fetch exposes one tool, `fetch(url, max_length=5000, start_index=0, raw=False)`, plus a matching prompt. Its interface is well defined. Arguments are typed and bounded (`max_length` must be between 1 and 999,999), and the tool is annotated as read-only and idempotent. Failures are predictable: a robots.txt refusal, an HTTP status of 400 or higher, or a private-network address each return a clear error, never empty content. Pagination through `start_index` also keeps output size under control.

Judged by the design principles from class, however, `fetch` bundles several responsibilities. It retrieves the page, enforces a robots.txt policy, simplifies HTML to Markdown, and truncates and paginates the result. The `raw` flag switches between two behaviours, a boolean mode flag that hints at "fetch *and* convert". The output is also an unstructured string with continuation instructions embedded in the text, not structured fields.

The bundling is still defensible: splitting conversion into a second tool would force large raw HTML through the model's context. Fetch shows good interface design and isolation (no side effects), trading single-purposeness for efficiency. I took that lesson into my own toolkit: keep each tool single-purpose with structured output, and do the combining in an explicit orchestration tool.
