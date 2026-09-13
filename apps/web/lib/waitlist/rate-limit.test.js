import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { consume, RATE_LIMIT, resetRateLimiter } from "./rate-limit.js";

describe("waitlist rate limiter", () => {
  beforeEach(() => {
    resetRateLimiter();
  });

  it("allows requests up to the window maximum", () => {
    for (
      let attempt = 0;
      attempt < RATE_LIMIT.MAX_REQUESTS_PER_WINDOW;
      attempt += 1
    ) {
      assert.equal(
        consume("1.2.3.4").allowed,
        true,
        `attempt ${attempt} should pass`,
      );
    }
  });

  it("blocks the request after the maximum is reached", () => {
    for (
      let attempt = 0;
      attempt < RATE_LIMIT.MAX_REQUESTS_PER_WINDOW;
      attempt += 1
    ) {
      consume("1.2.3.4");
    }

    const blocked = consume("1.2.3.4");

    assert.equal(blocked.allowed, false);
    assert.equal(blocked.remaining, 0);
    assert.ok(blocked.retryAfterSeconds > 0);
  });

  it("counts each client key separately", () => {
    for (
      let attempt = 0;
      attempt < RATE_LIMIT.MAX_REQUESTS_PER_WINDOW;
      attempt += 1
    ) {
      consume("1.2.3.4");
    }

    assert.equal(consume("1.2.3.4").allowed, false);
    assert.equal(consume("5.6.7.8").allowed, true);
  });

  it("lets a blocked client through once the window rolls over", () => {
    const start = 1_000_000;

    for (
      let attempt = 0;
      attempt < RATE_LIMIT.MAX_REQUESTS_PER_WINDOW;
      attempt += 1
    ) {
      consume("1.2.3.4", start);
    }

    assert.equal(consume("1.2.3.4", start).allowed, false);
    assert.equal(
      consume("1.2.3.4", start + RATE_LIMIT.WINDOW_MS + 1).allowed,
      true,
    );
  });

  it("reports the seconds remaining until the window resets", () => {
    const start = 1_000_000;

    for (
      let attempt = 0;
      attempt < RATE_LIMIT.MAX_REQUESTS_PER_WINDOW;
      attempt += 1
    ) {
      consume("1.2.3.4", start);
    }

    const blocked = consume("1.2.3.4", start + 60_000);

    assert.equal(
      blocked.retryAfterSeconds,
      (RATE_LIMIT.WINDOW_MS - 60_000) / 1000,
    );
  });
});
