/**
 * Manages connectivity to a Copium proxy (local or remote).
 *
 * Security model:
 * - Local proxies (127.0.0.1 / localhost) can be auto-started via subprocess
 * - Remote proxies are connect-only: probe and use, never launch
 * - No environment variable access
 */
import { spawn } from "node:child_process";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export interface ProxyManagerConfig {
  proxyUrl?: string;
  proxyPort?: number;
  pythonPath?: string;
  autoStart?: boolean;
  startupTimeoutMs?: number;
  retryMaxAttempts?: number;
  connectTimeoutSeconds?: number;
}

export interface ProxyManagerLogger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
  debug(message: string): void;
}

/** Default logger that prefixes all messages with `[copium]`. */
export const defaultLogger: ProxyManagerLogger = {
  info: (m) => console.log(`[copium] ${m}`),
  warn: (m) => console.warn(`[copium] ${m}`),
  error: (m) => console.error(`[copium] ${m}`),
  debug: () => {},
};

export interface ProxyProbeResult {
  reachable: boolean;
  isCopium: boolean;
  reason?: string;
}

interface LaunchSpec {
  label: string;
  command: string;
  args: string[];
  checkCommand: string;
  checkArgs: string[];
  useShell?: boolean;
  checkUseShell?: boolean;
}

const COPIUM_MODULE_DISCOVERY_SNIPPET =
  "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('copium') else 1)";

export class ProxyManager {
  private config: ProxyManagerConfig;
  private logger: ProxyManagerLogger;
  private proxyUrl: string | null = null;

  constructor(config: ProxyManagerConfig = {}, logger?: ProxyManagerLogger) {
    this.config = config;
    this.logger = logger ?? defaultLogger;
  }

  /**
   * Ensure a proxy is available. Returns the normalized URL origin.
   */
  async start(): Promise<string> {
    const port = this.getProxyPort();
    const rawExplicitUrl =
      typeof this.config.proxyUrl === "string" && this.config.proxyUrl.trim().length > 0
        ? normalizeAndValidateProxyUrl(this.config.proxyUrl)
        : null;
    // Only apply proxyPort default to local URLs — remote URLs use their protocol default
    const explicitUrl = rawExplicitUrl
      ? isLocalProxyUrl(rawExplicitUrl) ? withDefaultPort(rawExplicitUrl, port) : rawExplicitUrl
      : null;
    const defaultCandidates = this.getDefaultProxyCandidates(port);
    const candidateUrls = explicitUrl ? [explicitUrl] : [...defaultCandidates];
    const probeByUrl = new Map<string, ProxyProbeResult>();

    for (const url of candidateUrls) {
      const probe = await probeCopiumProxy(url);
      probeByUrl.set(url, probe);
      if (probe.reachable && probe.isCopium) {
        this.proxyUrl = url;
        this.logger.info(`Copium proxy already running at ${url}`);
        return url;
      }
    }

    if (explicitUrl) {
      const explicitProbe = probeByUrl.get(explicitUrl);
      if (explicitProbe?.reachable && !explicitProbe.isCopium) {
        throw new Error(
          `Service reachable at ${explicitUrl}, but it does not appear to be a Copium proxy (${explicitProbe.reason ?? "unknown service"}).`,
        );
      }
    }

    // Remote URLs are connect-only — never auto-start a subprocess for them
    if (explicitUrl && !isLocalProxyUrl(explicitUrl)) {
      throw new Error(
        `Remote Copium proxy not reachable at ${explicitUrl}. Ensure the proxy is running at that address.`,
      );
    }

    // Auto-start is only available for local proxies
    if (this.config.autoStart !== false) {
      const startupUrl = explicitUrl ?? defaultCandidates[0];
      const startupProbe = probeByUrl.get(startupUrl);
      if (startupProbe?.reachable && !startupProbe.isCopium) {
        throw new Error(
          `Cannot auto-start Copium at ${startupUrl}: port is in use by a non-Copium service (${startupProbe.reason ?? "unknown service"}).`,
        );
      }

      this.logger.info(
        `No Copium proxy detected${explicitUrl ? ` at ${startupUrl}` : " on default local endpoints"}; attempting to auto-start...`,
      );
      await this.startCopiumProxy(startupUrl, port);

      const startedProbe = await waitForCopiumProxy(
        startupUrl,
        this.config.startupTimeoutMs ?? 20_000,
      );
      if (startedProbe.reachable && startedProbe.isCopium) {
        this.proxyUrl = startupUrl;
        this.logger.info(`Copium proxy started and reachable at ${startupUrl}`);
        return startupUrl;
      }
      throw new Error(
        `Attempted to start Copium proxy, but it was not reachable at ${startupUrl} (${startedProbe.reason ?? "unknown"}).`,
      );
    }

    if (explicitUrl) {
      throw new Error(
        `Copium proxy not reachable at ${explicitUrl}. Ensure the proxy is running first.`,
      );
    }

    throw new Error(
      `Copium proxy not detected on default endpoints (${defaultCandidates.join(", ")}). ` +
        "Set proxyUrl explicitly or enable autoStart.",
    );
  }

  private getProxyPort(): number {
    const rawPort = this.config.proxyPort;
    if (!Number.isInteger(rawPort) || rawPort === undefined) return 8787;
    if (rawPort < 1 || rawPort > 65535) {
      throw new Error("proxyPort must be an integer between 1 and 65535");
    }
    return rawPort;
  }

  private getDefaultProxyCandidates(port: number): string[] {
    return [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
  }

  /**
   * Stop manager state. Spawned proxy processes are detached and externally managed.
   */
  async stop(): Promise<void> {
    this.proxyUrl = null;
  }

  getUrl(): string | null {
    return this.proxyUrl;
  }

  // --- Internal ---

  private async startCopiumProxy(proxyUrl: string, defaultPort: number): Promise<void> {
    const parsed = new URL(proxyUrl);
    const host = parsed.hostname;
    const port = parsed.port || String(defaultPort);
    const specs = this.buildLaunchSpecs(host, port);
    const errors: string[] = [];

    for (const spec of specs) {
      if (!this.canExecute(spec.checkCommand, spec.checkArgs, spec.checkUseShell ?? spec.useShell)) {
        this.logger.debug(`Launcher unavailable: ${spec.label}`);
        continue;
      }

      try {
        const child = spawn(spec.command, spec.args, {
          detached: true,
          shell: spec.useShell === true,
          stdio: "ignore",
        });
        child.unref();
        this.logger.info(`Auto-start launcher selected: ${spec.label}`);
        return;
      } catch (error) {
        errors.push(`${spec.label}: ${String(error)}`);
      }
    }

    throw new Error(
      "No usable Copium launcher found. Tried PATH, local npm, global npm, and Python. " +
        "Install copium-ai (npm or pip) and ensure one launcher is available.\n" +
        (errors.length > 0 ? `Launch errors: ${errors.join("; ")}` : ""),
    );
  }

  private buildLaunchSpecs(host: string, port: string): LaunchSpec[] {
    const commonArgs = ["proxy", "--host", host, "--port", port];
    const retryMaxAttempts = this.config.retryMaxAttempts;
    if (Number.isInteger(retryMaxAttempts)) {
      commonArgs.push("--retry-max-attempts", String(retryMaxAttempts));
    }

    const connectTimeoutSeconds = this.config.connectTimeoutSeconds;
    if (Number.isInteger(connectTimeoutSeconds)) {
      commonArgs.push("--connect-timeout-seconds", String(connectTimeoutSeconds));
    }

    const specs: LaunchSpec[] = [];

    const configuredPython = this.getConfiguredPythonCommand();
    if (configuredPython) {
      specs.push({
        label: `Configured Python: ${configuredPython} -m copium.cli`,
        command: configuredPython,
        args: ["-m", "copium.cli", ...commonArgs],
        checkCommand: configuredPython,
        checkArgs: ["-c", COPIUM_MODULE_DISCOVERY_SNIPPET],
      });
    }

    // 2) Windows pyenv: resolve the real executable so we avoid shim .bat wrappers.
    if (process.platform === "win32") {
      const pyenvCopium = this.getPyenvResolvedCopium();
      if (pyenvCopium) {
        specs.push({
          label: `pyenv: ${pyenvCopium}`,
          command: pyenvCopium,
          args: commonArgs,
          checkCommand: pyenvCopium,
          checkArgs: ["--version"],
          useShell: false,
        });
      }
    }

    // 3) PATH
    specs.push({
      label: "PATH: copium",
      command: "copium",
      args: commonArgs,
      checkCommand: process.platform === "win32" ? "where.exe" : "sh",
      checkArgs: process.platform === "win32"
        ? ["copium"]
        : ["-lc", "command -v copium >/dev/null 2>&1"],
      useShell: process.platform === "win32",
      checkUseShell: false,
    });

    // 4) Local npm install (inside plugin install path)
    const moduleDir = dirname(fileURLToPath(import.meta.url)); // .../dist
    const packageRoot = dirname(moduleDir);
    const localBinDir = join(packageRoot, "node_modules", ".bin");
    const localBins = process.platform === "win32"
      ? [join(localBinDir, "copium.cmd"), join(localBinDir, "copium")]
      : [join(localBinDir, "copium")];
    for (const localBin of localBins) {
      if (!existsSync(localBin)) continue;
        specs.push({
          label: `Local npm: ${localBin}`,
          command: localBin,
          args: commonArgs,
          checkCommand: localBin,
          checkArgs: ["--version"],
          useShell: process.platform === "win32",
        });
      }

    // 5) Global npm install
    const npmPrefix = this.getNpmGlobalPrefix();
    if (npmPrefix) {
      const globalBins = process.platform === "win32"
        ? [join(npmPrefix, "copium.cmd"), join(npmPrefix, "copium")]
        : [join(npmPrefix, "bin", "copium"), join(npmPrefix, "copium")];

      for (const globalBin of globalBins) {
        if (!existsSync(globalBin)) continue;
        specs.push({
          label: `Global npm: ${globalBin}`,
          command: globalBin,
          args: commonArgs,
          checkCommand: globalBin,
          checkArgs: ["--version"],
          useShell: process.platform === "win32",
        });
      }
    }

    // 6) Python module fallback
    const pythonCommands = this.getPythonCommands();
    for (const pyCmd of pythonCommands) {
      if (configuredPython && pyCmd === configuredPython) continue;
      specs.push({
        label: `Python: ${pyCmd} -m copium.cli`,
        command: pyCmd,
        args: ["-m", "copium.cli", ...commonArgs],
        checkCommand: pyCmd,
        checkArgs: ["-c", COPIUM_MODULE_DISCOVERY_SNIPPET],
      });
    }

    return specs;
  }

  private getConfiguredPythonCommand(): string | null {
    const configured = typeof this.config.pythonPath === "string"
      ? this.config.pythonPath.trim()
      : "";
    return configured.length > 0 ? configured : null;
  }

  private getPyenvResolvedCopium(): string | null {
    if (process.platform !== "win32") return null;

    try {
      const result = spawnSync("pyenv", ["which", "copium"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
        timeout: 5000,
      });
      if (result.error || result.status !== 0) return null;
      const resolved = (result.stdout ?? "").trim().split(/\r?\n/, 1)[0];
      if (!resolved || !existsSync(resolved)) return null;
      return resolved;
    } catch {
      return null;
    }
  }

  private getPythonCommands(): string[] {
    const commands: string[] = [];
    const configured = this.getConfiguredPythonCommand() ?? "";
    if (configured.length > 0) {
      commands.push(configured);
    }
    for (const fallback of ["python", "python3", "py"]) {
      if (!commands.includes(fallback)) commands.push(fallback);
    }
    return commands;
  }

  private canExecute(command: string, args: string[], useShell = false): boolean {
    try {
      const result = spawnSync(command, args, {
        shell: useShell,
        stdio: "ignore",
        timeout: 5000,
      });
      if (result.error) return false;
      return result.status === 0;
    } catch {
      return false;
    }
  }

  private getNpmGlobalPrefix(): string | null {
    try {
      const result = spawnSync("npm", ["prefix", "-g"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
        timeout: 5000,
      });
      if (result.error || result.status !== 0) return null;
      const prefix = (result.stdout ?? "").trim();
      return prefix.length > 0 ? prefix : null;
    } catch {
      return null;
    }
  }
}

/** Parse a URL, returning the parsed object or throwing a descriptive error. */
function parseProxyUrl(proxyUrl: string): URL {
  try {
    return new URL(proxyUrl);
  } catch {
    throw new Error(`Invalid proxyUrl: "${proxyUrl}"`);
  }
}

export function normalizeAndValidateProxyUrl(proxyUrl: string): string {
  const parsed = parseProxyUrl(proxyUrl);

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("proxyUrl must use http:// or https://");
  }

  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("proxyUrl must not include a path, query, or hash");
  }

  return parsed.origin;
}

/** Returns true if the URL points to a local address (localhost or 127.0.0.1). */
export function isLocalProxyUrl(proxyUrl: string): boolean {
  try {
    const parsed = new URL(proxyUrl);
    return parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost";
  } catch {
    return false;
  }
}

function withDefaultPort(proxyUrl: string, defaultPort: number): string {
  const parsed = parseProxyUrl(proxyUrl);
  if (!parsed.port) {
    parsed.port = String(defaultPort);
  }
  return parsed.origin;
}

/**
 * Probe a configured URL and verify whether it is a running Copium proxy.
 */
export async function probeCopiumProxy(proxyUrl: string): Promise<ProxyProbeResult> {
  const origin = normalizeAndValidateProxyUrl(proxyUrl);

  try {
    const health = await fetch(`${origin}/health`, {
      signal: AbortSignal.timeout(3_000),
    });
    if (!health.ok) {
      return { reachable: false, isCopium: false, reason: `health HTTP ${health.status}` };
    }
  } catch {
    return { reachable: false, isCopium: false, reason: "health check failed" };
  }

  try {
    const retrieveStats = await fetch(`${origin}/v1/retrieve/stats`, {
      signal: AbortSignal.timeout(3_000),
    });
    if (retrieveStats.ok) {
      return { reachable: true, isCopium: true };
    }
    return {
      reachable: true,
      isCopium: false,
      reason: `retrieve stats HTTP ${retrieveStats.status}`,
    };
  } catch {
    return {
      reachable: true,
      isCopium: false,
      reason: "retrieve stats endpoint unavailable",
    };
  }
}

async function waitForCopiumProxy(proxyUrl: string, timeoutMs: number): Promise<ProxyProbeResult> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const result = await probeCopiumProxy(proxyUrl);
    if (result.reachable && result.isCopium) {
      return result;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return probeCopiumProxy(proxyUrl);
}
