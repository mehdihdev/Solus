import { google } from "googleapis";

export const runtime = "nodejs";

const WAITLIST_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"];
const DEFAULT_RANGE = "Waitlist!A:C";

function getServiceAccountCredentials() {
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
    privateKey: privateKey?.replace(/\\n/g, "\n"),
  };
}

function validateEnvironment() {
  const spreadsheetId = process.env.GOOGLE_SHEETS_SPREADSHEET_ID;
  const range = process.env.GOOGLE_SHEETS_RANGE || DEFAULT_RANGE;
  const { clientEmail, privateKey } = getServiceAccountCredentials();

  if (!spreadsheetId || !clientEmail || !privateKey) {
    throw new Error(
      "Missing Google Sheets configuration. Set GOOGLE_SHEETS_SPREADSHEET_ID and service account credentials.",
    );
  }

  return {
    spreadsheetId,
    range,
    clientEmail,
    privateKey,
  };
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export async function POST(request) {
  try {
    const { email } = await request.json();
    const normalizedEmail = typeof email === "string" ? email.trim().toLowerCase() : "";

    if (!normalizedEmail || !isValidEmail(normalizedEmail)) {
      return Response.json(
        { message: "Enter a valid email address." },
        { status: 400 },
      );
    }

    const {
      spreadsheetId,
      range,
      clientEmail,
      privateKey,
    } = validateEnvironment();

    const auth = new google.auth.JWT({
      email: clientEmail,
      key: privateKey,
      scopes: WAITLIST_SCOPE,
    });

    const sheets = google.sheets({
      version: "v4",
      auth,
    });

    await sheets.spreadsheets.values.append({
      spreadsheetId,
      range,
      valueInputOption: "USER_ENTERED",
      insertDataOption: "INSERT_ROWS",
      requestBody: {
        values: [[normalizedEmail, new Date().toISOString(), "landing-page"]],
      },
    });

    return Response.json({
      message: "Thanks for joining the Solus Forge waitlist.",
    });
  } catch (error) {
    console.error("Failed to append waitlist signup", error);

    return Response.json(
      {
        message:
          "We could not save your email right now. Please try again in a moment.",
      },
      { status: 500 },
    );
  }
}

