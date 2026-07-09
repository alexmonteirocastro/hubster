import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatSource } from "../api/types";
import { SourceList } from "./SourceList";

const sampleSources: ChatSource[] = [
  {
    score: 0.91,
    job_id: "job-1",
    job_url: "https://thehub.io/jobs/job-1",
    job_role: "Backend Developer",
    job_title: "Senior Backend Developer",
    company: "Acme",
    country: "Denmark",
    location: "Copenhagen",
    document_text: "Job details…",
  },
];

describe("SourceList", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("uses compact chips when VITE_SHOW_DEBUG_SOURCES is false", () => {
    vi.stubEnv("VITE_SHOW_DEBUG_SOURCES", "false");

    render(<SourceList sources={sampleSources} />);

    expect(screen.getByText(/^sources$/i)).toBeInTheDocument();
    expect(screen.queryByText(/retrieved sources/i)).not.toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
  });

  it("uses compact chips when VITE_SHOW_DEBUG_SOURCES is unset", () => {
    render(<SourceList sources={sampleSources} />);

    const jobLink = screen.getByRole("link", { name: /senior backend developer/i });
    expect(jobLink).toHaveAttribute("href", "https://thehub.io/jobs/job-1");
    expect(screen.getByText("0.91")).toBeInTheDocument();
    expect(screen.getByText(/^sources$/i)).toBeInTheDocument();
    expect(screen.queryByText(/acme/i)).not.toBeInTheDocument();
  });

  it("renders full debug cards when variant is debug", () => {
    render(<SourceList sources={sampleSources} variant="debug" />);

    expect(screen.getByText(/retrieved sources/i)).toBeInTheDocument();
    expect(screen.getByText(/score 0\.91/i)).toBeInTheDocument();
    expect(screen.getByText(/acme · copenhagen · denmark/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /senior backend developer/i })).toBeInTheDocument();
  });

  it("renders full debug cards when VITE_SHOW_DEBUG_SOURCES is true", () => {
    vi.stubEnv("VITE_SHOW_DEBUG_SOURCES", "true");

    render(<SourceList sources={sampleSources} />);

    expect(screen.getByText(/retrieved sources/i)).toBeInTheDocument();
    expect(screen.getByText(/score 0\.91/i)).toBeInTheDocument();
  });
});
