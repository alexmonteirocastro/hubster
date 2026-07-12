import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_KEY_STORAGE_KEY } from "../api/authStorage";
import { ApiKeyModal } from "./ApiKeyModal";

vi.mock("../api/client", () => ({
  verifyApiKey: vi.fn(),
  ApiHttpError: class ApiHttpError extends Error {
    readonly status: number;
    constructor(status: number, message?: string) {
      super(message ?? `Request failed with status ${status}.`);
      this.name = "ApiHttpError";
      this.status = status;
    }
  },
  ApiNetworkError: class ApiNetworkError extends Error {
    constructor(message = "Unable to reach the API. Check your connection and try again.") {
      super(message);
      this.name = "ApiNetworkError";
    }
  },
}));

import { ApiHttpError, verifyApiKey } from "../api/client";

const mockVerifyApiKey = vi.mocked(verifyApiKey);

describe("ApiKeyModal", () => {
  beforeEach(() => {
    mockVerifyApiKey.mockReset();
    sessionStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows success state and close button after a valid key is verified", async () => {
    mockVerifyApiKey.mockResolvedValue(undefined);
    const onVerified = vi.fn();
    const user = userEvent.setup();

    render(<ApiKeyModal isOpen onClose={vi.fn()} onVerified={onVerified} />);

    await user.type(screen.getByLabelText(/api key/i), "valid-key");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByText(/api key verified/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close/i })).toBeInTheDocument();
    expect(onVerified).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBe("valid-key");
    expect(mockVerifyApiKey).toHaveBeenCalledWith("valid-key");
  });

  it("keeps the modal open with an error when the key is rejected", async () => {
    mockVerifyApiKey.mockRejectedValue(
      new ApiHttpError(401, "API key is not authorized."),
    );
    const user = userEvent.setup();

    render(<ApiKeyModal isOpen onClose={vi.fn()} onVerified={vi.fn()} />);

    await user.type(screen.getByLabelText(/api key/i), "bad-key");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /api key is not authorized/i,
    );
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
  });

  it("shows a client-side error for an empty key without calling verify", async () => {
    const user = userEvent.setup();

    render(<ApiKeyModal isOpen onClose={vi.fn()} onVerified={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/enter an api key/i);
    expect(mockVerifyApiKey).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
  });

  it("closes after success when the user clicks Close", async () => {
    mockVerifyApiKey.mockResolvedValue(undefined);
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<ApiKeyModal isOpen onClose={onClose} onVerified={vi.fn()} />);

    await user.type(screen.getByLabelText(/api key/i), "valid-key");
    await user.click(screen.getByRole("button", { name: /submit/i }));
    await user.click(await screen.findByRole("button", { name: /close/i }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it("allows cancel when dismiss is allowed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <ApiKeyModal isOpen allowDismiss onClose={onClose} onVerified={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not show cancel when dismiss is not allowed", () => {
    render(<ApiKeyModal isOpen onClose={vi.fn()} onVerified={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });

  it("closes on Escape when dismiss is allowed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <ApiKeyModal isOpen allowDismiss onClose={onClose} onVerified={vi.fn()} />,
    );

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
