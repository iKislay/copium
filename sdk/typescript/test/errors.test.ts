/**
 * Tests for error hierarchy — matches Python test_exceptions.py patterns.
 */
import { describe, it, expect } from "vitest";
import {
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
} from "../src/errors.js";

describe("CopiumError", () => {
  it("has correct name and message", () => {
    const err = new CopiumError("test error");
    expect(err.name).toBe("CopiumError");
    expect(err.message).toBe("test error");
    expect(err).toBeInstanceOf(Error);
  });

  it("supports details", () => {
    const err = new CopiumError("test", { key: "value" });
    expect(err.details).toEqual({ key: "value" });
  });

  it("details are optional", () => {
    const err = new CopiumError("test");
    expect(err.details).toBeUndefined();
  });
});

describe("CopiumConnectionError", () => {
  it("inherits from CopiumError", () => {
    const err = new CopiumConnectionError("connection failed");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("CopiumConnectionError");
  });
});

describe("CopiumAuthError", () => {
  it("inherits from CopiumError", () => {
    const err = new CopiumAuthError("unauthorized");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("CopiumAuthError");
  });
});

describe("CopiumCompressError", () => {
  it("includes statusCode and errorType", () => {
    const err = new CopiumCompressError(500, "compression_error", "failed");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("CopiumCompressError");
    expect(err.statusCode).toBe(500);
    expect(err.errorType).toBe("compression_error");
    expect(err.message).toBe("failed");
  });
});

describe("ConfigurationError", () => {
  it("inherits from CopiumError", () => {
    const err = new ConfigurationError("bad config");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("ConfigurationError");
  });
});

describe("ProviderError", () => {
  it("inherits from CopiumError", () => {
    const err = new ProviderError("provider failed");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("ProviderError");
  });
});

describe("StorageError", () => {
  it("inherits from CopiumError", () => {
    const err = new StorageError("db error");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("StorageError");
  });
});

describe("TokenizationError", () => {
  it("inherits from CopiumError", () => {
    const err = new TokenizationError("token count failed");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("TokenizationError");
  });
});

describe("CacheError", () => {
  it("inherits from CopiumError", () => {
    const err = new CacheError("cache miss");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("CacheError");
  });
});

describe("ValidationError", () => {
  it("inherits from CopiumError", () => {
    const err = new ValidationError("invalid setup");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("ValidationError");
  });
});

describe("TransformError", () => {
  it("inherits from CopiumError", () => {
    const err = new TransformError("transform failed");
    expect(err).toBeInstanceOf(CopiumError);
    expect(err.name).toBe("TransformError");
  });
});

describe("mapProxyError", () => {
  it("maps 401 to CopiumAuthError", () => {
    const err = mapProxyError(401, "auth_error", "unauthorized");
    expect(err).toBeInstanceOf(CopiumAuthError);
    expect(err.message).toBe("unauthorized");
  });

  it("maps configuration_error type", () => {
    const err = mapProxyError(400, "configuration_error", "bad config");
    expect(err).toBeInstanceOf(ConfigurationError);
  });

  it("maps provider_error type", () => {
    const err = mapProxyError(502, "provider_error", "upstream failed");
    expect(err).toBeInstanceOf(ProviderError);
  });

  it("maps storage_error type", () => {
    const err = mapProxyError(500, "storage_error", "db down");
    expect(err).toBeInstanceOf(StorageError);
  });

  it("maps tokenization_error type", () => {
    const err = mapProxyError(500, "tokenization_error", "bad tokens");
    expect(err).toBeInstanceOf(TokenizationError);
  });

  it("maps cache_error type", () => {
    const err = mapProxyError(500, "cache_error", "cache issue");
    expect(err).toBeInstanceOf(CacheError);
  });

  it("maps validation_error type", () => {
    const err = mapProxyError(422, "validation_error", "invalid");
    expect(err).toBeInstanceOf(ValidationError);
  });

  it("maps transform_error type", () => {
    const err = mapProxyError(500, "transform_error", "transform broke");
    expect(err).toBeInstanceOf(TransformError);
  });

  it("falls back to CopiumCompressError for unknown types", () => {
    const err = mapProxyError(500, "unknown_error", "something broke");
    expect(err).toBeInstanceOf(CopiumCompressError);
  });
});
