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
