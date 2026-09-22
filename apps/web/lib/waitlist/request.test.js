import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getClientKey,
  isValidEmail,
  MAX_BODY_BYTES,
  MAX_EMAIL_LENGTH,
  readJsonBody,
} from "./request.js";

function requestWith(body, headers = {}) {
  return new Request("https://solus.dev/api/waitlist", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body,
  });
}

describe("isValidEmail", () => {
  it("accepts an ordinary address", () => {
    assert.equal(isValidEmail("eng@robotics.dev"), true);
  });

  it("accepts a subdomain and a plus tag", () => {
    assert.equal(isValidEmail("eng+waitlist@mail.robotics.co.uk"), true);
  });

  for (const bad of [
    "",
    "no-at-sign.dev",
    "no-domain@",
    "@no-local.dev",
    "no tld@example",
    "spaces in@example.dev",
  ]) {
    it(`rejects ${JSON.stringify(bad)}`, () => {
      assert.equal(isValidEmail(bad), false);
    });
  }

  it("rejects an address longer than the RFC limit", () => {
    const tooLong = `${"a".repeat(MAX_EMAIL_LENGTH)}@example.dev`;

    assert.equal(isValidEmail(tooLong), false);
  });
});

describe("getClientKey", () => {
  it("uses the left-most x-forwarded-for entry", () => {
    const request = requestWith("{}", {
      "x-forwarded-for": "203.0.113.7, 70.41.3.18, 150.172.238.178",
    });

    assert.equal(getClientKey(request), "203.0.113.7");
  });

  it("falls back to x-real-ip", () => {
    const request = requestWith("{}", { "x-real-ip": "203.0.113.9" });

    assert.equal(getClientKey(request), "203.0.113.9");
  });

  it("returns a stable placeholder when no client header is present", () => {
    assert.equal(getClientKey(requestWith("{}")), "unknown");
  });
});

describe("readJsonBody", () => {
  it("parses a JSON object", async () => {
    const result = await readJsonBody(requestWith('{"email":"a@b.dev"}'));

    assert.deepEqual(result, { ok: true, value: { email: "a@b.dev" } });
  });

  it("rejects malformed JSON", async () => {
    const result = await readJsonBody(requestWith("{not json"));

    assert.equal(result.ok, false);
    assert.equal(result.reason, "malformed-json");
  });

  it("rejects a JSON array", async () => {
    const result = await readJsonBody(requestWith("[1,2,3]"));

    assert.equal(result.ok, false);
    assert.equal(result.reason, "not-an-object");
  });

  it("rejects a null body", async () => {
    const result = await readJsonBody(requestWith("null"));

    assert.equal(result.ok, false);
    assert.equal(result.reason, "not-an-object");
  });

  it("rejects a payload over the size cap", async () => {
    const oversized = JSON.stringify({ email: "a".repeat(MAX_BODY_BYTES) });
    const result = await readJsonBody(requestWith(oversized));

    assert.equal(result.ok, false);
    assert.equal(result.reason, "too-large");
  });
});
