# Differential Network Capture

Copium includes a containerized harness for comparing Claude Code traffic sent
directly to Anthropic with traffic sent through a Copium proxy. The harness
uses mitmproxy in two isolated lanes, writes sanitized JSONL captures, and then
generates Markdown/JSON reports with request route, header, body size, body hash,
and JSON payload differences.

## Run The Harness

```bash
cd docker/differential-network-capture
mkdir -p captures
export ANTHROPIC_API_KEY=...
export CLAUDE_PROMPT="Summarize this repository in one sentence."
docker compose up --build mitm-direct mitm-copium-upstream copium-proxy mitm-copium-client
docker compose --profile run run --rm claude-direct
docker compose --profile run run --rm claude-copium
```

The primary captures are written to:

- `docker/differential-network-capture/captures/direct.jsonl`
- `docker/differential-network-capture/captures/copium-client.jsonl`

The Copium lane also writes
`docker/differential-network-capture/captures/copium-upstream.jsonl`, which is
the request Copium forwards to Anthropic after proxy processing.

By default only `api.anthropic.com` is logged. Override
`CAPTURE_INCLUDE_HOSTS` with a comma-separated list to include other hosts.

## Generate A Report

```bash
copium capture network-diff \
  --direct docker/differential-network-capture/captures/direct.jsonl \
  --copium docker/differential-network-capture/captures/copium-client.jsonl \
  --output docker/differential-network-capture/captures/report.md \
  --json-output docker/differential-network-capture/captures/report.json
```

The report redacts sensitive header values and sensitive query values before
comparison. Request bodies are captured so structural payload differences can be
identified; keep the generated `captures/` directory out of commits because it
may contain prompts, tool outputs, and repository context.

For Claude Code deferred-tool investigations, the paired exchange table includes
top-level Anthropic `tools` counts and serialized tool bytes. A jump from
`tools=0->N` in the Copium client lane is evidence that Claude Code eagerly
materialized tool schemas before the request reached Copium.

## Custom Claude Invocation

Set `CLAUDE_COMMAND` to run the exact command under test in both lanes:

```bash
CLAUDE_COMMAND='claude -p "read README.md and summarize the proxy setup"' \
  docker compose --profile run run --rm claude-direct
CLAUDE_COMMAND='claude -p "read README.md and summarize the proxy setup"' \
  docker compose --profile run run --rm claude-copium
```

Use `CLAUDE_DIRECT_ARGS` and `CLAUDE_COPIUM_ARGS` when each lane needs
different flags.
