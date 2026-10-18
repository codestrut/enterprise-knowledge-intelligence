import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Workspace, { resolveCitationSources } from "./Workspace";
import groundedFixture from "./test-fixtures/query-grounded.json";
import refusalFixture from "./test-fixtures/query-refused.json";
import emptyRefusalFixture from "./test-fixtures/query-empty-refusal.json";
import { postQuery } from "./api/client";

const success = {
  question: "What is policy?",
  answer: "The policy sets a goal [Source 1]. A second point is listed [Source 2].",
  sources: [
    { text: "Policy goal passage", metadata: { source: "policy.pdf", page: 3, chunk_id: "a" } },
    { text: "Second source passage", metadata: { source: "guide.pdf", page: 8, chunk_id: "b" } },
  ],
  citations: [
    { source_number: 1, source: "policy.pdf", page: 3, chunk_id: "a" },
    { source_number: 2, source: "guide.pdf", page: 8, chunk_id: "b" },
  ],
  source_map: {
    "1": { source: "policy.pdf", page: 3, chunk_id: "a" },
    "2": { source: "guide.pdf", page: 8, chunk_id: "b" },
  },
  grounding: [
    { claim: "The policy sets a goal", status: "grounded", atomic_claims: [{ claim: "policy goal", status: "grounded", sources: [{ source_number: 1, label: "entailment", evidence: [{ label: "entailment", raw_label: "entailment", evidence: "Policy goal passage", evidence_score: 0.91 }, { evidence: "/app/data/uploads/private.pdf" }] }] }] },
    { claim: "The second point is listed", status: "unsupported", reason: "No supporting passage was found." },
  ],
  evidence: { sufficient: true, score: 4.8, threshold: 4.3, reason: "Evidence passed the relevance threshold." },
  refused: false,
  generation_repair: { attempted: false, accepted: false, reason: "initial_answer_passed_grounding" },
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function mockResponse(payload: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } })));
}

async function ask() {
  fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "What is policy?" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask EKIP" }));
}

describe("Knowledge workspace", () => {
  it("renders answers, verification counts, mapped citations and sources", async () => {
    mockResponse(success);
    render(<Workspace />);
    await ask();
    expect(await screen.findByRole("heading", { name: "Answer" })).toBeTruthy();
    expect(screen.getByText("1 of 2 claims marked grounded")).toBeTruthy();
    expect(screen.getAllByText("No supporting passage was found.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Go to Source 1" })).toBeTruthy();
    const verification = screen.getByRole("heading", { name: "Claim verification" }).closest("section");
    expect(verification).not.toBeNull();
    expect(within(verification!).getByText("Policy goal passage")).toBeTruthy();
    expect(within(verification!).queryByText("/app/data/uploads/private.pdf")).toBeNull();
    expect(within(verification!).getByText(/uncited = no citation was provided, so the claim is not verified/i)).toBeTruthy();
    expect(screen.getByText(/Backend evidence score: 4.8/)).toBeTruthy();
    const sourceCard = document.getElementById("source-1")!;
    sourceCard.scrollIntoView = vi.fn();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    fireEvent.click(screen.getByRole("button", { name: "Go to Source 1" }));
    expect(document.activeElement).toBe(sourceCard);
    fireEvent.click(screen.getByText("How this was checked"));
    expect(screen.queryByRole("heading", { name: "Claim checks" })).toBeNull();
  });

  it("separates cited sources from retrieved-but-uncited passages", async () => {
    mockResponse({
      answer: "The answer uses [Source 1].",
      sources: [
        { text: "Cited passage", metadata: { source: "cited.pdf", page: 1, chunk_id: "a" } },
        { text: "Retrieved from /app/data/private.pdf", metadata: { source: "other.pdf", page: 2, chunk_id: "b" } },
      ],
      citations: [{ source_number: 1, source: "cited.pdf", page: 1, chunk_id: "a" }],
      source_map: { "1": { source: "cited.pdf", page: 1, chunk_id: "a" } },
    });
    render(<Workspace />);
    await ask();
    await screen.findByRole("heading", { name: "Answer" });
    expect(screen.getByRole("heading", { name: "Sources cited in the answer" })).toBeTruthy();
    expect(screen.getByText("Cited passage")).toBeTruthy();
    const disclosure = screen.getByText("Retrieved, not cited (1)");
    expect(disclosure.closest("details")?.open).toBe(false);
    fireEvent.click(disclosure);
    expect(screen.getByText("Retrieved from private.pdf")).toBeTruthy();
    expect(screen.queryByText(/\/app\/data\/private\.pdf/)).toBeNull();
  });

  it.each([
    ["", 1],
    ["0", 1],
    ["-4", 1],
    ["21", 20],
  ])("keeps top_k in range when the input is %s", async (input, expected) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ answer: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Workspace />);
    fireEvent.change(screen.getByLabelText("Retrieved passages Choose 1 to 20 (default 5)"), { target: { value: input } });
    await ask();
    await screen.findByRole("heading", { name: "Answer" });
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body as string) as { top_k: number };
    expect(sent.top_k).toBe(expected);
    expect(Number.isFinite(sent.top_k) && sent.top_k >= 1 && sent.top_k <= 20).toBe(true);
  });

  it("does not issue a second request while a query is in flight", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    render(<Workspace />);
    await ask();
    const form = screen.getByLabelText("Your question").closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a non-JSON 504 message and retries through the existing action", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("<html>gateway</html>", { status: 504 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ answer: "Recovered answer." }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Workspace />);
    await ask();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("The server took too long to respond or is unavailable (HTTP 504). The query may still be running. Try again shortly.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Recovered answer.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("meets the real grounded response contract with a valid citation and nested evidence", async () => {
    mockResponse(groundedFixture);
    const response = await postQuery({ question: groundedFixture.question, top_k: 5 }, new AbortController().signal);
    expect(resolveCitationSources(response).size).toBeGreaterThan(0);
    const groundedClaim = response.grounding?.find((claim) => claim.status === "grounded");
    const nestedPassage = groundedClaim?.atomic_claims?.flatMap((claim) => claim.sources ?? [])
      .flatMap((source) => source.evidence ?? [])
      .find((entry) => typeof entry.evidence === "string")?.evidence;
    expect(nestedPassage).toEqual(expect.any(String));

    mockResponse(groundedFixture);
    render(<Workspace />);
    await ask();
    await screen.findByRole("heading", { name: "Answer" });
    expect(screen.getByRole("button", { name: /Go to Source/ })).toBeTruthy();
    const verification = screen.getByRole("heading", { name: "Claim verification" }).closest("section");
    expect(verification).not.toBeNull();
    expect(within(verification!).getByText(nestedPassage!)).toBeTruthy();
  });

  it("renders the real refusal fixture without exposing filesystem paths", async () => {
    mockResponse(refusalFixture);
    render(<Workspace />);
    await ask();
    expect(await screen.findByRole("heading", { name: "A sufficient answer wasn’t available" })).toBeTruthy();
    expect(screen.getByText(/did not support a sufficient answer/i)).toBeTruthy();
    expect(screen.getByText("Retrieved, not cited (5)")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/(?:^|\s)\/(?:app|Users|private|tmp)\//);
    expect(document.body.textContent).not.toMatch(/[A-Za-z]:\\/);
  });

  it("sanitizes filesystem paths in API-rendered answer text", async () => {
    mockResponse({ answer: "Stored at /app/data/uploads/private.pdf." });
    render(<Workspace />);
    await ask();
    expect(await screen.findByText("Stored at private.pdf.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("/app/data/uploads/private.pdf");
  });

  it("warns for unmapped citations and handles refusals with retrieved passages", async () => {
    mockResponse({ answer: "I don't have sufficient evidence [Source 1] [Source 4].", refused: true, evidence: { sufficient: false, reason: "Evidence was insufficient." }, sources: [{ text: "Related passage", metadata: { source: "/app/data/uploads/uuid.pdf", filename: "related.pdf", stored_filename: "uuid.pdf", page: 1 } }], citations: [{ source_number: 1, source: "different.pdf", page: 1 }] });
    render(<Workspace />);
    await ask();
    expect(await screen.findByRole("heading", { name: "A sufficient answer wasn’t available" })).toBeTruthy();
    expect(screen.getByText(/available documents did not support a sufficient answer/i)).toBeTruthy();
    expect(screen.getByText(/could not be matched to a returned source/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Go to Source 1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Go to Source 4" })).toBeNull();
    fireEvent.click(screen.getByText("Retrieved, not cited (1)"));
    expect(screen.getByRole("heading", { name: "related.pdf" })).toBeTruthy();
    expect(screen.getByText("Passages insufficient to support an answer")).toBeTruthy();
    expect(screen.queryByText("/internal/path/related.pdf")).toBeNull();
    expect(screen.queryByText("uuid.pdf")).toBeNull();
  });

  it("tolerates missing optional fields", async () => {
    mockResponse({ answer: "A short answer." });
    render(<Workspace />);
    await ask();
    expect(await screen.findByText("A short answer.")).toBeTruthy();
    expect(screen.getByText("No additional check details were returned.")).toBeTruthy();
  });

  it("shows API-reported invalid citation references only in the collapsed diagnostics", async () => {
    mockResponse({ answer: "A short answer.", invalid_citations: [4, 9] });
    render(<Workspace />);
    await ask();
    await screen.findByText("A short answer.");
    expect(screen.getByText("How this was checked").closest("details")?.open).toBe(false);
    fireEvent.click(screen.getByText("How this was checked"));
    expect(screen.getByText("The API reported invalid citation references: [Source 4], [Source 9].")).toBeTruthy();
  });

  it.each([undefined, []])("does not warn when invalid_citations is empty or missing (%s)", async (invalid_citations) => {
    mockResponse({ answer: "A short answer.", invalid_citations });
    render(<Workspace />);
    await ask();
    await screen.findByText("A short answer.");
    fireEvent.click(screen.getByText("How this was checked"));
    expect(screen.queryByText(/API reported invalid citation references/)).toBeNull();
  });

  it("does not present passages from an unsupported claim as verified evidence", async () => {
    mockResponse({
      answer: "A claim without support.",
      grounding: [{ claim: "A claim without support", status: "unsupported", atomic_claims: [{ sources: [{ source_number: 1, evidence: [{ evidence: "A passage that did not support the claim" }] }] }] }],
    });
    render(<Workspace />);
    await ask();
    await screen.findByRole("heading", { name: "Answer" });
    const verification = screen.getByRole("heading", { name: "Claim verification" }).closest("section");
    expect(verification).not.toBeNull();
    expect(within(verification!).getByText("unsupported")).toBeTruthy();
    expect(within(verification!).queryByText("A passage that did not support the claim")).toBeNull();
  });

  it("shows an empty-answer state for a response with no answer text", async () => {
    mockResponse({ answer: "  ", sources: [], citations: [], grounding: [] });
    render(<Workspace />);
    await ask();
    expect(await screen.findByText(/API returned no answer text/i)).toBeTruthy();
  });

  it("lets the user stop waiting and explains that server work may continue", async () => {
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    render(<Workspace />);
    await ask();
    fireEvent.click(screen.getByRole("button", { name: "Stop waiting" }));
    expect(await screen.findByText(/server may still be processing this query/i)).toBeTruthy();
  });

  it("distinguishes the 120-second client timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    render(<Workspace />);
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "slow question" } });
      fireEvent.click(screen.getByRole("button", { name: "Ask EKIP" }));
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(screen.getByText(/stopped waiting after 120 seconds/i)).toBeTruthy();
    vi.useRealTimers();
  });

  it("copies Markdown with footnotes for mapped sources", async () => {
    mockResponse(success);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<Workspace />);
    await ask();
    await screen.findByRole("heading", { name: "Answer" });
    fireEvent.click(screen.getByRole("button", { name: "Copy answer" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("[^1]: policy.pdf, p. 3")));
    expect(writeText.mock.calls[0][0]).toContain("[^2]: guide.pdf, p. 8");
    expect(writeText.mock.calls[0][0]).toContain("The policy sets a goal [^1].");
  });

  it("keeps the live empty-knowledge-base refusal behavior intact", async () => {
    mockResponse(emptyRefusalFixture);
    render(<Workspace/>);
    await ask();
    expect(await screen.findByRole("heading", { name: "A sufficient answer wasn’t available" })).toBeTruthy();
    expect(screen.getByText(/did not support a sufficient answer/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Go to Source/ })).toBeNull();
    expect(screen.getByText("I don't have sufficient evidence in the available knowledge base to answer that question.")).toBeTruthy();
  });
});

describe("citation source mapping", () => {
  const baseResult = {
    answer: "A fact [Source 1].",
    citations: [{ source_number: 1, source: "policy.pdf", page: 3, chunk_id: "chunk-a" }],
    source_map: { "1": { source: "policy.pdf", page: 3, chunk_id: "chunk-a" } },
    sources: [{ text: "Passage", metadata: { source: "policy.pdf", page: 3, chunk_id: "chunk-a" } }],
  };

  it("accepts a citation that agrees with the ranked source-map entry and source", () => {
    expect(resolveCitationSources(baseResult).get(1)?.source.text).toBe("Passage");
  });

  it("accepts the backend's numeric chunk-id shape", () => {
    const result = {
      ...baseResult,
      citations: [{ ...baseResult.citations[0], chunk_id: 30 }],
      source_map: { "1": { source: "policy.pdf", page: 3, chunk_id: 30 } },
      sources: [{ text: "Passage", metadata: { source: "policy.pdf", page: 3, chunk_id: 30 } }],
    };
    expect(resolveCitationSources(result).get(1)?.source.text).toBe("Passage");
  });

  it.each([
    ["source", { source: "other.pdf", page: 3, chunk_id: "chunk-a" }],
    ["page", { source: "policy.pdf", page: 4, chunk_id: "chunk-a" }],
    ["chunk", { source: "policy.pdf", page: 3, chunk_id: "chunk-b" }],
  ])("rejects a conflicting %s in the source-map record", (_field, entry) => {
    expect(resolveCitationSources({ ...baseResult, source_map: { "1": entry } }).has(1)).toBe(false);
  });

  it("rejects missing source-map entries", () => {
    expect(resolveCitationSources({ ...baseResult, source_map: {} }).size).toBe(0);
    expect(resolveCitationSources({ ...baseResult, source_map: { "2": baseResult.source_map["1"] } }).size).toBe(0);
  });

  it("rejects source metadata that disagrees with its ranked source-map entry", () => {
    const sources = [{ text: "Passage", metadata: { source: "other.pdf", page: 3, chunk_id: "chunk-a" } }];
    expect(resolveCitationSources({ ...baseResult, sources }).has(1)).toBe(false);
  });

  it("rejects citation metadata that disagrees with the source-map entry", () => {
    const citations = [{ ...baseResult.citations[0], chunk_id: "different-chunk" }];
    expect(resolveCitationSources({ ...baseResult, citations }).has(1)).toBe(false);
  });

  it.each([0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, 2])("rejects invalid or out-of-range source number %s", (source_number) => {
    const citation = { ...baseResult.citations[0], source_number };
    expect(resolveCitationSources({ ...baseResult, citations: [citation] }).size).toBe(0);
  });
});
