import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, postQuery, readApiDetail } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("query API client", () => {
  it("turns FastAPI validation arrays into readable errors", async () => {
    const errors = [{ loc: ["body", "top_k"], msg: "Input should be less than or equal to 20", type: "less_than_equal" }];
    expect(readApiDetail({ detail: errors })).toBe("body → top_k: Input should be less than or equal to 20");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: errors }), { status: 422 })));
    try {
      await postQuery({ question: "q", top_k: 21 }, new AbortController().signal);
      throw new Error("Expected the request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      expect((error as Error).message).toContain("body → top_k");
    }
  });

  it("handles string and object error details safely", () => {
    expect(readApiDetail({ detail: "Bad question" })).toBe("Bad question");
    expect(readApiDetail({ detail: { message: "Invalid request" } })).toBe("Invalid request");
    expect(readApiDetail({ detail: { unexpected: true } })).toBeUndefined();
  });
});
