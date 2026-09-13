import { consume } from "../../../lib/waitlist/rate-limit";
import {
  getClientKey,
  isValidEmail,
  readJsonBody,
} from "../../../lib/waitlist/request";
import { appendSignup } from "../../../lib/waitlist/sheet";

// googleapis needs Node APIs, so this route cannot run on the edge runtime.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SOURCE = "landing-page";

const MESSAGES = {
  success: "Thanks for joining the Solus waitlist.",
  invalidEmail: "Please enter a valid email address.",
  rateLimited: "Too many attempts. Please try again in a few minutes.",
  failure:
    "We could not save your email right now. Please try again in a moment.",
};

function json(body, status = 200, headers) {
  return Response.json(body, { status, headers });
}

/** Keeps the local part out of logs while staying useful for debugging. */
function redactEmail(email) {
  const [local, domain] = email.split("@");

  if (!domain) {
    return "<malformed>";
  }

  return `${local.slice(0, 2)}***@${domain}`;
}

export async function POST(request) {
  const clientKey = getClientKey(request);
  const limit = consume(clientKey);

  if (!limit.allowed) {
    return json({ message: MESSAGES.rateLimited }, 429, {
      "Retry-After": String(limit.retryAfterSeconds),
    });
  }

  const body = await readJsonBody(request);

  if (!body.ok) {
    return json({ message: MESSAGES.invalidEmail }, 400);
  }

  const { email, company } = body.value;

  // Honeypot: the field is off-screen and unlabelled, so a human never fills it.
  // Answer 200 so a bot cannot tell it was caught, but write nothing.
  if (typeof company === "string" && company.trim() !== "") {
    return json({ message: MESSAGES.success });
  }

  const normalizedEmail =
    typeof email === "string" ? email.trim().toLowerCase() : "";

  if (!isValidEmail(normalizedEmail)) {
    return json({ message: MESSAGES.invalidEmail }, 400);
  }

  try {
    await appendSignup({
      email: normalizedEmail,
      source: SOURCE,
      submittedAt: new Date(),
    });

    return json({ message: MESSAGES.success });
  } catch (error) {
    // Enough context to answer "why did this signup fail?" without leaking the
    // address or the service-account key.
    console.error("[waitlist] append failed", {
      code: error?.code,
      status: error?.status ?? error?.response?.status,
      message: error?.message,
      email: redactEmail(normalizedEmail),
    });

    return json({ message: MESSAGES.failure }, 500);
  }
}
