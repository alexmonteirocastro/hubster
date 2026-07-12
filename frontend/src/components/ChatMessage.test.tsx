import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChatMessage } from "./ChatMessage";

describe("ChatMessage", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders user content as plain text", () => {
    render(
      <ChatMessage
        message={{
          id: "user-1",
          role: "user",
          content: "**not bold**",
        }}
      />,
    );

    expect(screen.getByText("**not bold**")).toBeInTheDocument();
    expect(screen.queryByRole("strong")).not.toBeInTheDocument();
  });

  it("renders assistant bold markdown as a strong element", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-1",
          role: "assistant",
          content: "**Backend Software Engineer** at Acme",
        }}
      />,
    );

    const strong = screen.getByRole("strong");
    expect(strong).toHaveTextContent("Backend Software Engineer");
    expect(screen.queryByText("**Backend Software Engineer**")).not.toBeInTheDocument();
  });

  it("renders assistant inline markdown links without stray punctuation", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-3",
          role: "assistant",
          content:
            "[Sales Development Representative](https://thehub.io/jobs/job-1) looks like the closest match.",
        }}
      />,
    );

    const link = screen.getByRole("link", { name: /sales development representative/i });
    expect(link).toHaveAttribute("href", "https://thehub.io/jobs/job-1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/looks like the closest match/i)).toBeInTheDocument();
    expect(screen.queryByText(/\)\s*looks/i)).not.toBeInTheDocument();
  });

  it("does not render img elements for assistant markdown images", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-4",
          role: "assistant",
          content: "![tracking pixel](https://evil.example/pixel.gif)",
        }}
      />,
    );

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders assistant bullet lists as ul/li elements", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-2",
          role: "assistant",
          content: "- Senior Backend Developer\n- Platform Engineer",
        }}
      />,
    );

    const list = screen.getByRole("list");
    expect(list.tagName).toBe("UL");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Senior Backend Developer")).toBeInTheDocument();
    expect(screen.getByText("Platform Engineer")).toBeInTheDocument();
  });
});
