import { afterEach, describe, expect, it, vi } from "vitest";
import { createMessageId } from "./id";

describe("createMessageId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses crypto.randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "test-uuid" });
    expect(createMessageId()).toBe("test-uuid");
  });

  it("falls back when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {});
    expect(createMessageId()).toMatch(/^msg-\d+-[a-z0-9]+$/);
  });
});
