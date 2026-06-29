# MCP Compression Proxy

Copium includes an MCP proxy mode that sits between your AI coding tool and your upstream MCP servers.

Architecture:

Agent -> Copium MCP Proxy -> Upstream MCP Servers

The proxy transparently compresses:

- Tool descriptions (typically 70-90 percent reduction)
- Tool schemas (typically ~57 percent reduction)
- Tool call responses (typically 60-95 percent reduction)
- Repeated definitions through session deduplication (typically 95-99 percent reduction)

It also supports progressive tool disclosure:

- Send compact tool stubs first
- Discover tools with `copium_find_tool`
- Request full schema on demand with `copium_get_tool_schema`

## CLI

Start proxy server:

```bash
copium mcp proxy serve
```

Install proxy into detected agents:

```bash
copium mcp proxy install
```

Install for one agent:

```bash
copium mcp proxy install --agent claude-code
```

Detect available agents:

```bash
copium mcp proxy detect
```

Show proxy status:

```bash
copium mcp proxy status
```

## Configuration

Default config path:

`~/.copium/mcp-proxy.json`

Example:

```json
{
  "upstream_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  },
  "compression": {
    "descriptions": true,
    "schemas": true,
    "responses": true,
    "progressive_disclosure": true,
    "session_dedup": true
  }
}
```

## Internal Proxy Tools

The proxy exposes helper tools to the host:

- `copium_find_tool`
- `copium_get_tool_schema`
- `copium_retrieve`
- `copium_proxy_stats`

These work alongside upstream tools and are designed to minimize context overhead during long sessions.