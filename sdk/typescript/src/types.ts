/**
 * Core types for the Copium TypeScript SDK.
 * Error classes moved to errors.ts — re-exported here for backwards compatibility.
 */

import type { CompressionHooks } from "./hooks.js";

// --- Message types (OpenAI chat format) ---

export interface TextContentPart {
  type: "text";
  text: string;
}

export interface ImageContentPart {
  type: "image_url";
  image_url: { url: string; detail?: "auto" | "low" | "high" };
}

export type ContentPart = TextContentPart | ImageContentPart;

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export interface SystemMessage {
  role: "system";
  content: string;
}

export interface UserMessage {
  role: "user";
  content: string | ContentPart[];
}

export interface AssistantMessage {
  role: "assistant";
  content: string | null;
  tool_calls?: ToolCall[];
}

export interface ToolMessage {
  role: "tool";
  content: string;
  tool_call_id: string;
}

export type OpenAIMessage =
  | SystemMessage
  | UserMessage
  | AssistantMessage
  | ToolMessage;

// --- Compress API ---

export interface CompressOptions {
  model?: string;
  baseUrl?: string;
  apiKey?: string;
  timeout?: number;
  fallback?: boolean;
  retries?: number;
  client?: CopiumClientInterface;
  /** Token budget — compress to fit within this limit. Used for compaction. */
  tokenBudget?: number;
  /** Compression hooks for pre/post processing. */
  hooks?: CompressionHooks;
  /** Integration slug sent as X-Copium-Stack (e.g. "adapter_ts_openai"). */
  stack?: string;
}

export interface CompressResult {
  /** Compressed messages in the same format as input. */
  messages: any[];
  tokensBefore: number;
  tokensAfter: number;
  tokensSaved: number;
  compressionRatio: number;
  transformsApplied: string[];
  ccrHashes: string[];
  compressed: boolean;
}

// --- Client ---

export interface CopiumClientOptions {
  baseUrl?: string;
  apiKey?: string;
  timeout?: number;
  fallback?: boolean;
  retries?: number;
  /** Integration slug sent as X-Copium-Stack on every request. */
  stack?: string;
}

export interface CopiumClientInterface {
  compress(
    messages: OpenAIMessage[],
    options?: { model?: string; tokenBudget?: number },
  ): Promise<CompressResult>;
}

// --- Re-export errors for backwards compatibility ---

export {
  CopiumError,
  CopiumConnectionError,
  CopiumAuthError,
  CopiumCompressError,
  ConfigurationError,
  ProviderError,
  StorageError,
  TokenizationError,
  CacheError,
  ValidationError,
  TransformError,
  mapProxyError,
} from "./errors.js";

// --- Proxy response (internal) ---

export interface ProxyCompressResponse {
  messages: OpenAIMessage[];
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  compression_ratio: number;
  transforms_applied: string[];
  ccr_hashes: string[];
}

export interface ProxyErrorResponse {
  error: {
    type: string;
    message: string;
  };
}
