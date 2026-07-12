import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_KEY_STORAGE_KEY,
  clearStoredApiKey,
  getStoredApiKey,
  hasStoredApiKey,
  setStoredApiKey,
} from "./authStorage";
import {
  ApiHttpError,
  ApiNetworkError,
  ApiTimeoutError,
  postChat,
  setUnauthorizedHandler,
  verifyApiKey,
} from "./client";

describe("authStorage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stores and clears the API key in sessionStorage", () => {
    expect(hasStoredApiKey()).toBe(false);
    setStoredApiKey("abc123");
    expect(getStoredApiKey()).toBe("abc123");
    expect(hasStoredApiKey()).toBe(true);
    clearStoredApiKey();
    expect(hasStoredApiKey()).toBe(false);
  });
});

describe("verifyApiKey", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls jobs stats with the bearer token", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ total_jobs: 1, remote_jobs: 0, jobs_per_role: {} }),
    } as Response);

    await verifyApiKey("test-key");

    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/stats?country=SE",
      expect.objectContaining({
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-key",
        },
      }),
    );
  });

  it("throws ApiHttpError when the key is rejected", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      json: () =>
        Promise.resolve({
          detail: { message: "API key is not authorized.", code: "invalid_api_key" },
        }),
    } as Response);

    await expect(verifyApiKey("bad-key")).rejects.toMatchObject({
      status: 401,
      message: "API key is not authorized.",
    });
  });
});

describe("postChat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    sessionStorage.clear();
    setUnauthorizedHandler(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
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

  it("sends Authorization when a key is stored", async () => {
    setStoredApiKey("stored-key");
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          question: "hello",
          answer: "ok",
          sources: [],
          generated: true,
        }),
    } as Response);

    await postChat({ question: "hello" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer stored-key",
        }),
      }),
    );
  });

  it("throws ApiNetworkError when fetch fails", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(postChat({ question: "hello" })).rejects.toBeInstanceOf(ApiNetworkError);
  });

  it("throws ApiTimeoutError when the request is aborted", async () => {
    vi.mocked(fetch).mockRejectedValue(new DOMException("Aborted", "AbortError"));

    await expect(postChat({ question: "hello" })).rejects.toBeInstanceOf(
      ApiTimeoutError,
    );
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

  it("parses structured auth error detail on 401", async () => {
    setStoredApiKey("old-key");
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      json: () =>
        Promise.resolve({
          detail: { message: "API key is not authorized.", code: "invalid_api_key" },
        }),
    } as Response);

    await expect(postChat({ question: "hello" })).rejects.toMatchObject({
      status: 401,
      message: "API key is not authorized.",
    });
  });

  it("clears storage and invokes the unauthorized handler on 401", async () => {
    setStoredApiKey("old-key");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      json: () =>
        Promise.resolve({
          detail: { message: "API key is not authorized.", code: "invalid_api_key" },
        }),
    } as Response);

    await expect(postChat({ question: "hello" })).rejects.toBeInstanceOf(ApiHttpError);
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
