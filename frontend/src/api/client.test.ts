import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiNetworkError, ApiTimeoutError, postChat } from "./client";

describe("postChat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed response on success", async () => {
    const body = {
      question: "backend roles?",
      answer: "Here are some roles.",
      sources: [],
      generated: true,
    };
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(body),
    } as Response);

    await expect(postChat({ question: "backend roles?" })).resolves.toEqual(body);
    expect(fetch).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "backend roles?" }),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("throws ApiNetworkError when fetch fails", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(postChat({ question: "hello" })).rejects.toBeInstanceOf(ApiNetworkError);
  });

  it("throws ApiTimeoutError when the request is aborted", async () => {
    vi.mocked(fetch).mockRejectedValue(new DOMException("Aborted", "AbortError"));

    await expect(postChat({ question: "hello" })).rejects.toBeInstanceOf(ApiTimeoutError);
  });

  it("throws ApiHttpError with a rate-limit message on 429", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 429,
      json: () => Promise.resolve({}),
    } as Response);

    await expect(postChat({ question: "hello" })).rejects.toMatchObject({
      status: 429,
      message: "The service is rate-limited. Please wait a moment and try again.",
    });
  });

  it("throws ApiHttpError with a generic server message on 5xx without detail", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.resolve({}),
    } as Response);

    await expect(postChat({ question: "hello" })).rejects.toMatchObject({
      status: 502,
      message: "The server encountered an error. Please try again later.",
    });
  });

  it("parses Pydantic-style 422 validation detail arrays", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 422,
      json: () =>
        Promise.resolve({
          detail: [
            {
              type: "string_too_long",
              loc: ["body", "question"],
              msg: "String should have at most 5 characters",
              input: "toolong",
              ctx: { max_length: 5 },
            },
          ],
        }),
    } as Response);

    await expect(postChat({ question: "toolong" })).rejects.toMatchObject({
      status: 422,
      message: "String should have at most 5 characters",
    });
  });

  it("prefers API error detail over the default message on 429", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 429,
      json: () =>
        Promise.resolve({
          detail: "The generation service is rate-limited. Please try again shortly.",
        }),
    } as Response);

    await expect(postChat({ question: "hello" })).rejects.toMatchObject({
      status: 429,
      message: "The generation service is rate-limited. Please try again shortly.",
    });
  });
});
