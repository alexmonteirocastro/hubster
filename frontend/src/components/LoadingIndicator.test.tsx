import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoadingIndicator } from "./LoadingIndicator";

describe("LoadingIndicator", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("renders the default local-generation-aware message when VITE_LOADING_MESSAGE is unset", () => {
    render(<LoadingIndicator />);

    expect(screen.getByRole("status")).toHaveTextContent(
      /searching jobs and generating an answer.*local models may take a few minutes/i,
    );
  });

  it("renders the configured VITE_LOADING_MESSAGE", () => {
    vi.stubEnv(
      "VITE_LOADING_MESSAGE",
      "Searching and thinking — this can take a few moments, thanks for your patience.",
    );

    render(<LoadingIndicator />);

    expect(screen.getByRole("status")).toHaveTextContent(
      /searching and thinking — this can take a few moments, thanks for your patience/i,
    );
  });
});
