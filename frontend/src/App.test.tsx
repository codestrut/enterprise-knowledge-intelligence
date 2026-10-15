import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("API health overview", () => {
  it("shows live health metrics after a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "ok",
            document_count: 14,
            chunk_count: 86,
            manifest_exists: true,
            failed_document_count: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<App />);

    expect(await screen.findByText("Operational")).toBeTruthy();
    expect(screen.getByText("14")).toBeTruthy();
    expect(screen.getByText("86")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.getByText("Manifest available")).toBeTruthy();
  });

  it("shows unavailable when the API cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    render(<App />);

    expect(await screen.findByText("Backend unavailable")).toBeTruthy();
    expect(screen.queryByText("Operational")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("serves the workspace at /workspace while keeping the overview at /", () => {
    window.history.replaceState({}, "", "/workspace");
    render(<App />);
    expect(screen.getByRole("heading", { name: "Ask your knowledge base" })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "System overview" }).every((link) => link.getAttribute("href") === "/")).toBe(true);
  });
});
