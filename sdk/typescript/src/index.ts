// --- Core ---
export { compress } from "./compress.js";
export { CopiumClient } from "./client.js";
export type { ExtendedClientOptions, CopiumParams } from "./client.js";
export { simulate } from "./simulate.js";
export type { SimulateOptions } from "./simulate.js";

// --- Format utilities ---
export { detectFormat, toOpenAI, fromOpenAI } from "./utils/format.js";
export type { MessageFormat } from "./utils/format.js";

// --- Case conversion utilities ---
export { deepCamelCase, deepSnakeCase, snakeToCamel, camelToSnake } from "./utils/case.js";

// --- Streaming utilities ---
export { parseSSE, collectStream } from "./utils/stream.js";

// --- Core types ---
export type {
  TextContentPart,
  ImageContentPart,
  ContentPart,
  ToolCall,
  SystemMessage,
  UserMessage,
  AssistantMessage,
  ToolMessage,
  OpenAIMessage,
  CompressOptions,
  CompressResult,
  CopiumClientOptions,
  CopiumClientInterface,
} from "./types.js";

// --- Errors (full hierarchy) ---
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

// --- Config types ---
export type {
  CopiumMode,
  RelevanceTier,
  ContentType,
  BlockKind,
  ToolCrusherConfig,
  CacheAlignerConfig,
  RollingWindowConfig,
  ScoringWeights,
  IntelligentContextConfig,
  RelevanceScorerConfig,
  AnchorConfig,
  SmartCrusherConfig,
  CacheOptimizerConfig,
  CCRConfig,
  PrefixFreezeConfig,
  ReadLifecycleConfig,
  CompressionProfile,
  CopiumConfig,
} from "./types/config.js";

// --- Data models ---
export type {
  WasteSignals,
  CachePrefixMetrics,
  TransformDiff,
  DiffArtifact,
  SimulationResult,
  RequestMetrics,
  Block,
  SessionStats,
  ValidationResult,
  MetricsSummary,
  HealthStatus,
  ProxyStats,
  MemoryUsage,
  RetrieveResult,
  RetrieveSearchResult,
  CCRStats,
  TelemetryStats,
  ToolHints,
  TOINStats,
  TOINPattern,
  MetricsQuery,
  SummaryQuery,
  StatsHistoryQuery,
} from "./types/models.js";

// --- Hooks ---
export { CompressionHooks, extractUserQuery, countTurns, extractToolCalls } from "./hooks.js";
export type { CompressContext, CompressEvent } from "./hooks.js";

// --- SharedContext ---
export { SharedContext } from "./shared-context.js";
export type {
  ContextEntry,
  SharedContextStats,
  SharedContextOptions,
} from "./shared-context.js";

// --- Filesystem contract (parity shell with copium.paths) ---
export {
  COPIUM_CONFIG_DIR_ENV,
  COPIUM_WORKSPACE_DIR_ENV,
  COPIUM_SAVINGS_PATH_ENV,
  COPIUM_TOIN_PATH_ENV,
  COPIUM_SUBSCRIPTION_STATE_PATH_ENV,
  configDir,
  workspaceDir,
  savingsPath,
  toinPath,
  subscriptionStatePath,
  memoryDbPath,
  nativeMemoryDir,
  licenseCachePath,
  sessionStatsPath,
  syncStatePath,
  bridgeStatePath,
  logDir,
  proxyLogPath,
  debug400Dir,
  binDir,
  rtkPath,
  deployRoot,
  beaconLockPath,
  modelsConfigPath,
  pluginConfigDir,
  pluginWorkspaceDir,
} from "./paths.js";
