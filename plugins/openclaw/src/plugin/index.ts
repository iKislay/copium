/**
 * Copium OpenClaw Plugin — register ContextEngine + CCR retrieval tool.
 *
 * Usage:
 *   openclaw plugins install copium-ai/openclaw
 *
 * Configuration (in ~/.openclaw/config.json or ~/.clawdbot/clawdbot.json):
 *   {
 *     "plugins": {
 *       "slots": { "contextEngine": "copium" },
 *       "entries": { "copium": { "enabled": true } }
 *     }
 *   }
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import { CopiumContextEngine } from "../engine.js";
import {
  applyGatewayProviderBaseUrlsInPlace,
  resolveGatewayProviderIds,
} from "../gateway-config.js";
import { normalizeAndValidateProxyUrl } from "../proxy-manager.js";
import { createCopiumRetrieveTool } from "../tools/copium-retrieve.js";

export default function copiumPlugin(api: any) {
  const config = api.config?.plugins?.entries?.copium?.config ?? {};
  const logger = api.logger ?? console;
  const rawProxyUrl = config.proxyUrl;
  const proxyUrl =
    typeof rawProxyUrl === "string" && rawProxyUrl.trim().length > 0
      ? normalizeAndValidateProxyUrl(rawProxyUrl)
      : undefined;

  const engine = new CopiumContextEngine({ ...config, proxyUrl }, {
    info: (m: string) => logger.info(m),
    warn: (m: string) => logger.warn(m),
    error: (m: string) => logger.error(m),
    debug: (m: string) => logger.debug?.(m),
  });
  const gatewayProviderIds = resolveGatewayProviderIds(config);

  const applyGatewayRouting = async (activeProxyUrl: string) => {
    if (gatewayProviderIds.length === 0) {
      return;
    }

    try {
      const changed = applyGatewayProviderBaseUrlsInPlace(api.config, activeProxyUrl, gatewayProviderIds);

      if (changed) {
        logger.info(
          `[copium] Routed ${gatewayProviderIds.join(", ")} through Copium proxy in memory at ${activeProxyUrl}`,
        );
      } else {
        logger.info(
          `[copium] Upstream gateway already routed in memory for ${gatewayProviderIds.join(", ")} at ${activeProxyUrl}`,
        );
      }
    } catch (error) {
      logger.warn(`[copium] Failed to configure upstream gateway routing: ${error}`);
    }
  };

  const ensureGatewayRouting = async () => {
    const activeProxyUrl = engine.getProxyUrl();
    if (!activeProxyUrl) {
      logger.debug?.("[copium] Deferring upstream gateway routing until proxy is available");
      engine.ensureProxyStarted();
      return;
    }
    await applyGatewayRouting(activeProxyUrl);
  };

  engine.onProxyReady(async (activeProxyUrl) => {
    await applyGatewayRouting(activeProxyUrl);
  });

  // Register as context engine
  api.registerContextEngine("copium", () => engine);

  // Register CCR retrieval tool (active once proxy is running)
  api.registerTool((ctx: any) => {
    const activeProxyUrl = engine.getProxyUrl() ?? proxyUrl;
    if (!activeProxyUrl) return null;
    return createCopiumRetrieveTool({ proxyUrl: activeProxyUrl });
  });

  api.on("gateway_start", async () => {
    await ensureGatewayRouting();
  });

  void ensureGatewayRouting();

  logger.info("[copium] Plugin registered");
}
