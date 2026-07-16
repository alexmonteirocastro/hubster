import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CHAT_QUESTION_MAX_LENGTH } from "../api/client";
import { ChatInput } from "./ChatInput";
import styles from "./ChatInput.module.css";

describe("ChatInput", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders a live character counter at 0/max by default", () => {
    render(<ChatInput onSubmit={vi.fn()} disabled={false} />);

    expect(screen.getByText(`0/${CHAT_QUESTION_MAX_LENGTH}`)).toBeInTheDocument();
  });

  it("updates the character counter as the user types", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSubmit={vi.fn()} disabled={false} />);

    await user.type(screen.getByLabelText(/ask a question about jobs/i), "hello");

    expect(screen.getByText(`5/${CHAT_QUESTION_MAX_LENGTH}`)).toBeInTheDocument();
  });

  it("hard-caps the textarea via maxLength matching the configured limit", () => {
    render(<ChatInput onSubmit={vi.fn()} disabled={false} />);

    expect(screen.getByLabelText(/ask a question about jobs/i)).toHaveAttribute(
      "maxLength",
      String(CHAT_QUESTION_MAX_LENGTH),
    );
  });

  it("does not accept more characters than maxLength when pasting", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSubmit={vi.fn()} disabled={false} />);

    const input = screen.getByLabelText(/ask a question about jobs/i);
    await user.click(input);
    await user.paste("a".repeat(CHAT_QUESTION_MAX_LENGTH + 20));

    expect(input).toHaveValue("a".repeat(CHAT_QUESTION_MAX_LENGTH));
    expect(
      screen.getByText(`${CHAT_QUESTION_MAX_LENGTH}/${CHAT_QUESTION_MAX_LENGTH}`),
    ).toBeInTheDocument();
  });

  it("keeps the counter silent for screen readers until near the limit", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSubmit={vi.fn()} disabled={false} />);

    expect(screen.getByText(`0/${CHAT_QUESTION_MAX_LENGTH}`)).not.toHaveAttribute("aria-live");

    const nearLimitCount = Math.floor(CHAT_QUESTION_MAX_LENGTH * 0.9);
    const input = screen.getByLabelText(/ask a question about jobs/i);
    await user.click(input);
    await user.paste("a".repeat(nearLimitCount));

    const counter = screen.getByText(`${nearLimitCount}/${CHAT_QUESTION_MAX_LENGTH}`);
    expect(counter.className).toContain(styles.counterNearLimit);
    expect(counter).toHaveAttribute("aria-live", "polite");
  });

  it("submits the trimmed question when under the limit and clears the input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText(/ask a question about jobs/i), "  backend roles  ");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    expect(onSubmit).toHaveBeenCalledWith("backend roles");
    expect(screen.getByLabelText(/ask a question about jobs/i)).toHaveValue("");
    expect(screen.getByText(`0/${CHAT_QUESTION_MAX_LENGTH}`)).toBeInTheDocument();
  });

  it("submits normally when the question is exactly at the character limit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const exact = "a".repeat(CHAT_QUESTION_MAX_LENGTH);
    render(<ChatInput onSubmit={onSubmit} disabled={false} />);

    const input = screen.getByLabelText(/ask a question about jobs/i);
    await user.click(input);
    await user.paste(exact);
    await user.click(screen.getByRole("button", { name: /ask/i }));

    expect(onSubmit).toHaveBeenCalledWith(exact);
  });
});
