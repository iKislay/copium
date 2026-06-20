export { default } from "./plugin/index.js";
export { CopiumContextEngine } from "./engine.js";
export { ProxyManager, normalizeAndValidateProxyUrl, isLocalProxyUrl, defaultLogger, probeCopiumProxy } from "./proxy-manager.js";
export { agentToOpenAI, normalizeAgentMessages, openAIToAgent } from "./convert.js";
export { createCopiumRetrieveTool } from "./tools/copium-retrieve.js";
export {
  DEFAULT_GATEWAY_PROVIDER_IDS,
  applyGatewayProviderBaseUrls,
  applyGatewayProviderBaseUrlsInPlace,
  resolveGatewayProviderIds,
} from "./gateway-config.js";
