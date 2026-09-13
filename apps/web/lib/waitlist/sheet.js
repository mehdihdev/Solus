import { google } from "googleapis";

/** Google Sheets persistence for waitlist signups. */

const SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"];
const DEFAULT_RANGE = "Waitlist!A:C";

function readServiceAccount() {
  const json = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;

  if (json) {
    const parsed = JSON.parse(json);

    return {
      clientEmail: parsed.client_email,
      privateKey: parsed.private_key,
    };
  }

  const clientEmail = process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL;
  const privateKey = process.env.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY;

  return {
    clientEmail,
    // Dashboards and .env files carry the key with literal \n escapes.
    privateKey: privateKey?.replace(/\\n/g, "\n"),
  };
}

/**
 * @returns {{ spreadsheetId: string, range: string, clientEmail: string, privateKey: string }}
 * @throws {Error} when the deployment is missing Sheets configuration.
 */
export function readSheetConfig() {
  const spreadsheetId = process.env.GOOGLE_SHEETS_SPREADSHEET_ID;
  const range = process.env.GOOGLE_SHEETS_RANGE || DEFAULT_RANGE;
  const { clientEmail, privateKey } = readServiceAccount();

  const missing = [
    !spreadsheetId && "GOOGLE_SHEETS_SPREADSHEET_ID",
    !clientEmail &&
      "GOOGLE_SERVICE_ACCOUNT_JSON (or GOOGLE_SERVICE_ACCOUNT_EMAIL)",
    !privateKey &&
      "GOOGLE_SERVICE_ACCOUNT_JSON (or GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY)",
  ].filter(Boolean);

  if (missing.length > 0) {
    const error = new Error(
      `Waitlist is not configured. Missing: ${missing.join(", ")}.`,
    );
    error.code = "WAITLIST_NOT_CONFIGURED";
    throw error;
  }

  return { spreadsheetId, range, clientEmail, privateKey };
}

/**
 * Appends one signup row: email, ISO timestamp, source.
 *
 * @param {{ email: string, source: string, submittedAt: Date }} signup
 */
export async function appendSignup({ email, source, submittedAt }) {
  const { spreadsheetId, range, clientEmail, privateKey } = readSheetConfig();

  const auth = new google.auth.JWT({
    email: clientEmail,
    key: privateKey,
    scopes: SHEETS_SCOPE,
  });

  const sheets = google.sheets({ version: "v4", auth });

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range,
    // RAW keeps the address verbatim; USER_ENTERED lets Sheets coerce values
    // and turns a leading "=" or "+" into a formula.
    valueInputOption: "RAW",
    insertDataOption: "INSERT_ROWS",
    requestBody: {
      values: [[email, submittedAt.toISOString(), source]],
    },
  });
}
