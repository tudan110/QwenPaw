import { describe, it, expect } from "vitest";
import {
  auditCsvCell,
  endpointOrigin,
  redactForDisplay,
  safeDisplayText,
} from "./evidenceDisplay";

describe("evidence display boundaries", () => {
  it("retains only URL origins, including IPv6", () => {
    expect(
      endpointOrigin(
        "https://user:password@example.invalid:8443/private?token=secret#fragment",
      ),
    ).toBe("https://example.invalid:8443");
    expect(endpointOrigin("http://[::1]:8080/path")).toBe("http://[::1]:8080");
    expect(endpointOrigin("malformed")).toBe("[hidden]");
  });
  it.each([
    ["Authorization: Bearer bearer-secret", "bearer-secret"],
    ["Authorization: Basic encoded-secret", "encoded-secret"],
    ["password='secret with spaces'", "secret with spaces"],
    ["curl --access-token cli-secret", "cli-secret"],
    [
      "https://user:url-secret@demo.invalid/private?token=query-secret",
      "query-secret",
    ],
    [
      "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
      "private-material",
    ],
  ])("masks free text: %s", (text, secret) =>
    expect(safeDisplayText(text)).not.toContain(secret),
  );
  it("masks nested credentials without mutating original approval parameters", () => {
    const source = {
      path: "/safe/file.txt",
      nested: [{ apiKey: "secret-one" }],
      headers: { "X-Custom": "secret-two" },
      env: { NORMAL_NAME: "secret-three" },
      attempts: 2,
    };
    const before = JSON.stringify(source);
    const display = JSON.stringify(redactForDisplay(source));
    expect(JSON.stringify(source)).toBe(before);
    expect(display).toContain("/safe/file.txt");
    expect(display).toContain('"attempts":2');
    for (const secret of ["secret-one", "secret-two", "secret-three"])
      expect(display).not.toContain(secret);
  });
  it("keeps the URL path needed to review an approval scope", () => {
    const text = safeDisplayText(
      "https://user:password@example.invalid:8443/reports/*?token=secret#private",
    );
    expect(text).toContain("https://example.invalid:8443/reports/*");
    expect(text).not.toContain("password");
    expect(text).not.toContain("secret");
    expect(text).not.toContain("private");
  });
  it.each(["=HYPERLINK(1)", "+1+2", "-1+2", "@SUM(A1)", " \t=1+1", "\r=1"])(
    "neutralizes spreadsheet formulas: %s",
    (value) => expect(auditCsvCell(value)).toMatch(/^"'/),
  );
  it("quotes commas, newlines and double quotes in CSV values", () => {
    expect(auditCsvCell('one,"two"\nthree')).toBe('"one,""two""\nthree"');
  });
});
