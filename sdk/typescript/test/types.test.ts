import { describe, it, expectTypeOf } from "vitest";
import type {
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
  ProxyCompressResponse,
  ProxyErrorResponse,
} from "../src/types.js";
import {
  CopiumError,
  CopiumConnectionError,
  CopiumAuthError,
  CopiumCompressError,
} from "../src/types.js";

describe("Message types", () => {
  it("TextContentPart has correct shape", () => {
    expectTypeOf<TextContentPart>().toMatchTypeOf<{ type: "text"; text: string }>();
  });

  it("ImageContentPart has correct shape", () => {
    expectTypeOf<ImageContentPart>().toHaveProperty("type");
    expectTypeOf<ImageContentPart>().toHaveProperty("image_url");
    expectTypeOf<ImageContentPart["image_url"]>().toHaveProperty("url");
    expectTypeOf<ImageContentPart["image_url"]["detail"]>().toEqualTypeOf<
      "auto" | "low" | "high" | undefined
    >();
  });

  it("ContentPart is union of Text and Image", () => {
    expectTypeOf<TextContentPart>().toMatchTypeOf<ContentPart>();
    expectTypeOf<ImageContentPart>().toMatchTypeOf<ContentPart>();
  });

  it("ToolCall has correct shape", () => {
    expectTypeOf<ToolCall>().toHaveProperty("id");
    expectTypeOf<ToolCall>().toHaveProperty("type");
    expectTypeOf<ToolCall>().toHaveProperty("function");
    expectTypeOf<ToolCall["type"]>().toEqualTypeOf<"function">();
    expectTypeOf<ToolCall["function"]>().toEqualTypeOf<{
      name: string;
      arguments: string;
    }>();
  });

  it("SystemMessage has role system and string content", () => {
    expectTypeOf<SystemMessage["role"]>().toEqualTypeOf<"system">();
    expectTypeOf<SystemMessage["content"]>().toBeString();
  });

  it("UserMessage content can be string or ContentPart[]", () => {
    expectTypeOf<UserMessage["role"]>().toEqualTypeOf<"user">();
    expectTypeOf<UserMessage["content"]>().toEqualTypeOf<
      string | ContentPart[]
    >();
  });

  it("AssistantMessage content can be string or null", () => {
    expectTypeOf<AssistantMessage["role"]>().toEqualTypeOf<"assistant">();
    expectTypeOf<AssistantMessage["content"]>().toEqualTypeOf<string | null>();
  });

  it("AssistantMessage tool_calls is optional", () => {
    expectTypeOf<AssistantMessage["tool_calls"]>().toEqualTypeOf<
      ToolCall[] | undefined
    >();
  });

  it("ToolMessage has tool_call_id", () => {
    expectTypeOf<ToolMessage["role"]>().toEqualTypeOf<"tool">();
    expectTypeOf<ToolMessage>().toHaveProperty("tool_call_id");
    expectTypeOf<ToolMessage["tool_call_id"]>().toBeString();
  });

  it("OpenAIMessage is union of all message types", () => {
    expectTypeOf<SystemMessage>().toMatchTypeOf<OpenAIMessage>();
    expectTypeOf<UserMessage>().toMatchTypeOf<OpenAIMessage>();
    expectTypeOf<AssistantMessage>().toMatchTypeOf<OpenAIMessage>();
    expectTypeOf<ToolMessage>().toMatchTypeOf<OpenAIMessage>();
  });
});

describe("CompressOptions", () => {
  it("all fields are optional", () => {
    expectTypeOf<CompressOptions>().toMatchTypeOf<{}>();
  });

  it("has expected optional fields", () => {
    expectTypeOf<CompressOptions["model"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<CompressOptions["baseUrl"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<CompressOptions["apiKey"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<CompressOptions["timeout"]>().toEqualTypeOf<
      number | undefined
    >();
    expectTypeOf<CompressOptions["fallback"]>().toEqualTypeOf<
      boolean | undefined
    >();
    expectTypeOf<CompressOptions["retries"]>().toEqualTypeOf<
      number | undefined
    >();
    expectTypeOf<CompressOptions["client"]>().toEqualTypeOf<
      CopiumClientInterface | undefined
    >();
  });
});

describe("CompressResult", () => {
  it("has all required fields with correct types", () => {
    expectTypeOf<CompressResult>().toHaveProperty("messages");
    expectTypeOf<CompressResult["messages"]>().toEqualTypeOf<OpenAIMessage[]>();
    expectTypeOf<CompressResult["tokensBefore"]>().toBeNumber();
    expectTypeOf<CompressResult["tokensAfter"]>().toBeNumber();
    expectTypeOf<CompressResult["tokensSaved"]>().toBeNumber();
    expectTypeOf<CompressResult["compressionRatio"]>().toBeNumber();
    expectTypeOf<CompressResult["transformsApplied"]>().toEqualTypeOf<
      string[]
    >();
    expectTypeOf<CompressResult["ccrHashes"]>().toEqualTypeOf<string[]>();
    expectTypeOf<CompressResult["compressed"]>().toBeBoolean();
  });
});

describe("CopiumClientOptions", () => {
  it("all fields are optional", () => {
    expectTypeOf<CopiumClientOptions>().toMatchTypeOf<{}>();
  });

  it("has expected optional fields", () => {
    expectTypeOf<CopiumClientOptions["baseUrl"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<CopiumClientOptions["apiKey"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<CopiumClientOptions["timeout"]>().toEqualTypeOf<
      number | undefined
    >();
    expectTypeOf<CopiumClientOptions["fallback"]>().toEqualTypeOf<
      boolean | undefined
    >();
    expectTypeOf<CopiumClientOptions["retries"]>().toEqualTypeOf<
      number | undefined
    >();
  });
});

describe("CopiumClientInterface", () => {
  it("has compress method", () => {
    expectTypeOf<CopiumClientInterface>().toHaveProperty("compress");
  });

  it("compress returns Promise<CompressResult>", () => {
    expectTypeOf<CopiumClientInterface["compress"]>().returns.toEqualTypeOf<
      Promise<CompressResult>
    >();
  });

  it("compress accepts messages and optional options", () => {
    expectTypeOf<CopiumClientInterface["compress"]>().parameters.toEqualTypeOf<
      [OpenAIMessage[], ({ model?: string } | undefined)?]
    >();
  });
});

describe("Error classes", () => {
  it("CopiumError extends Error", () => {
    expectTypeOf<CopiumError>().toMatchTypeOf<Error>();
  });

  it("CopiumConnectionError extends CopiumError", () => {
    expectTypeOf<CopiumConnectionError>().toMatchTypeOf<CopiumError>();
  });

  it("CopiumAuthError extends CopiumError", () => {
    expectTypeOf<CopiumAuthError>().toMatchTypeOf<CopiumError>();
  });

  it("CopiumCompressError extends CopiumError", () => {
    expectTypeOf<CopiumCompressError>().toMatchTypeOf<CopiumError>();
  });

  it("CopiumCompressError has statusCode and errorType", () => {
    expectTypeOf<CopiumCompressError>().toHaveProperty("statusCode");
    expectTypeOf<CopiumCompressError["statusCode"]>().toBeNumber();
    expectTypeOf<CopiumCompressError>().toHaveProperty("errorType");
    expectTypeOf<CopiumCompressError["errorType"]>().toBeString();
  });

  it("error classes are constructable", () => {
    const err = new CopiumError("test");
    expectTypeOf(err).toMatchTypeOf<Error>();

    const connErr = new CopiumConnectionError("test");
    expectTypeOf(connErr).toMatchTypeOf<CopiumError>();

    const authErr = new CopiumAuthError("test");
    expectTypeOf(authErr).toMatchTypeOf<CopiumError>();

    const compressErr = new CopiumCompressError(500, "server_error", "test");
    expectTypeOf(compressErr).toMatchTypeOf<CopiumError>();
    expectTypeOf(compressErr.statusCode).toBeNumber();
    expectTypeOf(compressErr.errorType).toBeString();
  });
});

describe("Proxy response types (internal)", () => {
  it("ProxyCompressResponse uses snake_case", () => {
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("tokens_before");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("tokens_after");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("tokens_saved");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("compression_ratio");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("transforms_applied");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("ccr_hashes");
    expectTypeOf<ProxyCompressResponse>().toHaveProperty("messages");
    expectTypeOf<ProxyCompressResponse["tokens_before"]>().toBeNumber();
    expectTypeOf<ProxyCompressResponse["messages"]>().toEqualTypeOf<
      OpenAIMessage[]
    >();
  });

  it("ProxyErrorResponse has error with type and message", () => {
    expectTypeOf<ProxyErrorResponse>().toHaveProperty("error");
    expectTypeOf<ProxyErrorResponse["error"]>().toEqualTypeOf<{
      type: string;
      message: string;
    }>();
  });
});
