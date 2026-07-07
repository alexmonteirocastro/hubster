import type { ChatRequest, ChatResponse } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiNetworkError extends Error {
  constructor(message = "Unable to reach the API. Check your connection and try again.") {
    super(message);
    this.name = "ApiNetworkError";
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

function defaultHttpMessage(status: number): string {
  if (status === 429) {
    return "The service is rate-limited. Please wait a moment and try again.";
  }
  if (status >= 500) {
    return "The server encountered an error. Please try again later.";
  }
  return `Request failed with status ${status}.`;
}

async function parseErrorDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: string | { msg: string }[] };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      return body.detail.map((item) => item.msg).join("; ");
    }
  } catch {
    // Response body is not JSON — fall back to generic message.
  }
  return undefined;
}

export async function postChat(request: ChatRequest): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new ApiNetworkError();
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiHttpError(response.status, detail);
  }

  return (await response.json()) as ChatResponse;
}
