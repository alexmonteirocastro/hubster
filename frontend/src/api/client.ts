import { clearStoredApiKey, getStoredApiKey } from "./authStorage";
import type { ChatRequest, ChatResponse } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

/** Default for local dev / Ollama; production builds set VITE_CHAT_REQUEST_TIMEOUT_MS via .env.production. */
export const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = 600_000;

function parseChatRequestTimeoutMs(): number {
  const raw = import.meta.env.VITE_CHAT_REQUEST_TIMEOUT_MS;
  if (raw === undefined || raw === "") {
    return DEFAULT_CHAT_REQUEST_TIMEOUT_MS;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_CHAT_REQUEST_TIMEOUT_MS;
  }
  return parsed;
}

/** Browser-side /chat fetch timeout; should be ≥ the proxy timeout in each environment. */
export const CHAT_REQUEST_TIMEOUT_MS = parseChatRequestTimeoutMs();

export class ApiNetworkError extends Error {
  constructor(message = "Unable to reach the API. Check your connection and try again.") {
    super(message);
    this.name = "ApiNetworkError";
  }
}

export class ApiTimeoutError extends ApiNetworkError {
  constructor(
    message = "The request timed out. Local generation can take several minutes — please try again.",
  ) {
    super(message);
    this.name = "ApiTimeoutError";
  }
}

export class ApiHttpError extends Error {
  readonly status: number;

  constructor(status: number, detail?: string) {
    const message = detail ?? defaultHttpMessage(status);
    super(message);
    this.name = "ApiHttpError";
    this.status = status;
  }
}

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function defaultHttpMessage(status: number): string {
  if (status === 401) {
    return "API key is not authorized.";
  }
  if (status === 429) {
    return "The service is rate-limited. Please wait a moment and try again.";
  }
  if (status >= 500) {
    return "The server encountered an error. Please try again later.";
  }
  return `Request failed with status ${status}.`;
}

function buildAuthHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...extra,
  };
  const apiKey = getStoredApiKey();
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }
  return headers;
}

export async function parseErrorDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as {
      detail?: string | { msg: string }[] | { message: string; code?: string };
    };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (
      typeof body.detail === "object" &&
      body.detail !== null &&
      !Array.isArray(body.detail) &&
      "message" in body.detail
    ) {
      return body.detail.message;
    }
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      return body.detail.map((item) => item.msg).join("; ");
    }
  } catch {
    // Response body is not JSON — fall back to generic message.
  }
  return undefined;
}

function handleUnauthorizedResponse(): void {
  clearStoredApiKey();
  unauthorizedHandler?.();
}

async function readErrorResponse(response: Response): Promise<never> {
  const detail = await parseErrorDetail(response);
  throw new ApiHttpError(response.status, detail);
}

export async function verifyApiKey(apiKey: string): Promise<void> {
  let response: Response;
  try {
    // SE is arbitrary — verifyApiKey only checks auth via response.ok, not stats data.
    response = await fetch(`${API_BASE_URL}/jobs/stats?country=SE`, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
    });
  } catch {
    throw new ApiNetworkError();
  }

  if (!response.ok) {
    await readErrorResponse(response);
  }
}

export async function postChat(request: ChatRequest): Promise<ChatResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CHAT_REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: buildAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiTimeoutError();
    }
    throw new ApiNetworkError();
  } finally {
    clearTimeout(timeoutId);
  }

  if (response.status === 401) {
    handleUnauthorizedResponse();
    await readErrorResponse(response);
  }

  if (!response.ok) {
    await readErrorResponse(response);
  }

  return (await response.json()) as ChatResponse;
}
