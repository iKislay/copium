# TypeScript SDK

The Copium TypeScript SDK lets any JavaScript or TypeScript application compress LLM messages before sending them to a model. It saves tokens, reduces costs, and fits more context into every request.

## Install

```bash
npm install copium-ai
```

Requires a running [Copium proxy](proxy.md) or Copium Cloud API key.

## Quick Start

```typescript
import { compress } from 'copium-ai';

const result = await compress(messages, { model: 'gpt-4o' });
console.log(`Saved ${result.tokensSaved} tokens`);

const response = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: result.messages,
});
```

## How It Works

The TypeScript SDK is an HTTP client. When you call `compress()`, it sends your messages to the Copium proxy's `POST /v1/compress` endpoint. The proxy runs the full compression pipeline (SmartCrusher, ContentRouter, CacheAligner, etc.) and returns compressed messages. No compression logic runs in Node.js — all the heavy lifting happens in the proxy.

```
Your TypeScript App
    │
    │  compress(messages)
    ▼
copium-ai (npm)  ← HTTP client
    │
    │  POST /v1/compress
    ▼
Copium Proxy / Cloud  ← compression pipeline (Python)
    │
    │  compressed messages
    ▼
Your TypeScript App
    │
    │  openai.chat.completions.create(compressed)
    ▼
LLM Provider
```

## Core API: `compress()`

```typescript
import { compress } from 'copium-ai';

const result = await compress(messages, {
  model: 'gpt-4o',                      // model name (for token counting)
  baseUrl: 'http://localhost:8787',      // proxy URL (default)
  apiKey: 'hr_...',                      // Copium Cloud key
  timeout: 30000,                        // ms (default)
  fallback: true,                        // return uncompressed if proxy down (default)
  retries: 1,                            // retry on transient errors (default)
});

result.messages          // compressed messages (same format as input)
result.tokensBefore      // original token count
result.tokensAfter       // compressed token count
result.tokensSaved       // tokens removed
result.compressionRatio  // tokensAfter / tokensBefore
result.transformsApplied // e.g. ['router:smart_crusher:0.35']
result.compressed        // false if fallback kicked in
```

Messages use standard OpenAI chat format: `{ role, content, tool_calls?, tool_call_id? }`.

### Environment Variables

Instead of passing options, set environment variables:

- `COPIUM_BASE_URL` — proxy or cloud URL (default: `http://localhost:8787`)
- `COPIUM_API_KEY` — Copium Cloud API key

## Reusable Client

For apps making many calls, create a client once and reuse it:

```typescript
import { CopiumClient } from 'copium-ai';

const client = new CopiumClient({
  baseUrl: 'http://localhost:8787',
  apiKey: 'hr_...',
});

const r1 = await client.compress(messages1, { model: 'gpt-4o' });
const r2 = await client.compress(messages2, { model: 'gpt-4o' });
```

## Framework Adapters

### Vercel AI SDK

The Copium middleware plugs directly into Vercel AI SDK's `wrapLanguageModel()`:

```typescript
import { copiumMiddleware } from 'copium-ai/vercel-ai';
import { wrapLanguageModel, generateText } from 'ai';
import { openai } from '@ai-sdk/openai';

const model = wrapLanguageModel({
  model: openai('gpt-4o'),
  middleware: copiumMiddleware(),
});

// All calls through this model are automatically compressed
const { text } = await generateText({ model, messages });
```

The middleware intercepts messages in the `transformParams` hook, converts Vercel's internal format to OpenAI format, compresses via the proxy, and converts back. Your app code doesn't change.

You can also compress Vercel messages directly:

```typescript
import { compressVercelMessages } from 'copium-ai/vercel-ai';

const result = await compressVercelMessages(modelMessages, { model: 'gpt-4o' });
// result.messages is in Vercel ModelMessage[] format
```

### OpenAI SDK

Wrap your OpenAI client to auto-compress messages on every `chat.completions.create()` call:

```typescript
import { withCopium } from 'copium-ai/openai';
import OpenAI from 'openai';

const client = withCopium(new OpenAI());

// Messages are compressed before sending — transparent to your code
const response = await client.chat.completions.create({
  model: 'gpt-4o',
  messages: longConversation,
});
```

Only `chat.completions.create()` is intercepted. All other methods (embeddings, images, audio) pass through unchanged.

### Anthropic SDK

Same pattern for the Anthropic client:

```typescript
import { withCopium } from 'copium-ai/anthropic';
import Anthropic from '@anthropic-ai/sdk';

const client = withCopium(new Anthropic());

const response = await client.messages.create({
  model: 'claude-sonnet-4-5-20250929',
  messages: longConversation,
  max_tokens: 1024,
});
```

Only `messages.create()` is intercepted. The adapter converts between Anthropic's content block format and OpenAI format automatically.

## Error Handling

```typescript
import { compress, CopiumConnectionError, CopiumAuthError } from 'copium-ai';

try {
  const result = await compress(messages, { model: 'gpt-4o', fallback: false });
} catch (error) {
  if (error instanceof CopiumAuthError) {
    // Invalid API key (401)
  } else if (error instanceof CopiumConnectionError) {
    // Proxy unreachable
  }
}
```

With `fallback: true` (the default), connection errors and 5xx responses return the original messages uncompressed instead of throwing. Auth errors (401) and client errors (400) always throw.

## Fallback Behavior

By default, `compress()` never blocks your app. If the proxy is unreachable:

| Scenario | `fallback: true` (default) | `fallback: false` |
|----------|---------------------------|-------------------|
| Proxy unreachable | Returns uncompressed, `compressed: false` | Throws `CopiumConnectionError` |
| Proxy 503 error | Returns uncompressed after retries | Throws `CopiumCompressError` |
| Invalid API key (401) | Throws `CopiumAuthError` | Throws `CopiumAuthError` |
| Bad request (400) | Throws `CopiumCompressError` | Throws `CopiumCompressError` |

## Zero Dependencies

The `copium-ai` package has no runtime dependencies. Framework SDKs (Vercel AI, OpenAI, Anthropic) are optional peer dependencies — only install what you use.

## OpenClaw Plugin

The TypeScript SDK powers the [`copium-openclaw`](https://www.npmjs.com/package/copium-openclaw) plugin for [OpenClaw](https://github.com/openclaw/openclaw) agents. The plugin uses `CopiumClient` internally to compress context during the `assemble()` lifecycle hook. The preferred install flow is `copium wrap openclaw`; the direct plugin command is `openclaw plugins install --dangerously-force-unsafe-install copium-ai/openclaw`. See the [plugin source](https://github.com/iKislay/copium/tree/main/plugins/openclaw) for details.

## Comparison with Python SDK

| Feature | Python SDK | TypeScript SDK |
|---------|-----------|---------------|
| `compress()` | Native (runs locally) | HTTP client (calls proxy) |
| Proxy | Built-in server | Connects to proxy |
| Vercel AI SDK | N/A | Middleware adapter |
| OpenAI SDK | `CopiumClient` wrapper | `withCopium()` wrapper |
| Anthropic SDK | `CopiumClient` wrapper | `withCopium()` wrapper |
| LangChain | `CopiumChatModel` | Use `compress()` directly |
| Memory system | Full (SQLite + HNSW) | Not yet (use proxy) |
| MCP server | Built-in | Not yet |
| CLI tools | `copium proxy`, `copium wrap`, etc. | N/A (use Python CLI) |
