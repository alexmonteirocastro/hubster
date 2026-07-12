import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_KEY_STORAGE_KEY, setStoredApiKey } from "./api/authStorage";
import App from "./App";

describe("App auth wiring", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    sessionStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("reopens the modal on a 401 from postChat without showing a chat error", async () => {
    setStoredApiKey("stored-key");
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      json: () =>
        Promise.resolve({
          detail: { message: "API key is not authorized.", code: "invalid_api_key" },
        }),
    } as Response);
    const user = userEvent.setup();

    render(<App />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/ask a question about jobs/i), "hello");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(screen.queryByText(/api key is not authorized/i)).not.toBeInTheDocument();
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
  });
});
