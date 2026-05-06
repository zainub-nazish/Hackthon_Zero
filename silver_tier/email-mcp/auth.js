/**
 * auth.js — One-time OAuth2 consent helper.
 *
 * Run ONCE to generate token.json:
 *   node auth.js
 *
 * This opens a browser for Google consent and saves the refresh token
 * to ../token.json (project root), which index.js reads automatically.
 */

import { readFileSync, writeFileSync } from "fs";
import { createServer }               from "http";
import { URL }                        from "url";
import { google }                     from "googleapis";
import path                           from "path";
import { fileURLToPath }              from "url";

const __dirname   = path.dirname(fileURLToPath(import.meta.url));
const VAULT_ROOT  = path.resolve(__dirname, "..");
const CREDS_FILE  = path.join(VAULT_ROOT, "credentials.json");
const TOKEN_FILE  = path.join(VAULT_ROOT, "token.json");

const SCOPES = [
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/gmail.compose",
  "https://www.googleapis.com/auth/gmail.readonly",
];

const PORT = 8765;

async function main() {
  // Load credentials.json
  let creds;
  try {
    creds = JSON.parse(readFileSync(CREDS_FILE, "utf8"));
  } catch {
    console.error(`ERROR: Cannot read ${CREDS_FILE}`);
    console.error("Download credentials.json from Google Cloud Console (OAuth2 Desktop App).");
    process.exit(1);
  }

  const { client_id, client_secret, redirect_uris } = creds.installed ?? creds.web;
  const redirectUri = `http://localhost:${PORT}`;

  const oauth2 = new google.auth.OAuth2(client_id, client_secret, redirectUri);

  const authUrl = oauth2.generateAuthUrl({
    access_type:  "offline",
    scope:        SCOPES,
    prompt:       "consent",   // force refresh_token to be returned every time
  });

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("  Gmail OAuth2 Setup");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("\nOpening browser for Google consent...");
  console.log(`\nIf browser doesn't open, visit:\n  ${authUrl}\n`);

  // Open browser (Windows / Mac / Linux)
  const open = (url) => {
    const cmd =
      process.platform === "win32" ? `start "" "${url}"` :
      process.platform === "darwin" ? `open "${url}"` :
      `xdg-open "${url}"`;
    import("child_process").then(({ execSync }) => {
      try { execSync(cmd); } catch { /* ignore */ }
    });
  };
  open(authUrl);

  // Start a one-shot local HTTP server to capture the OAuth callback
  const code = await new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      const url = new URL(req.url, `http://localhost:${PORT}`);
      const code = url.searchParams.get("code");
      const err  = url.searchParams.get("error");

      if (err) {
        res.end(`<h2>Auth failed: ${err}</h2>`);
        server.close();
        reject(new Error(`OAuth error: ${err}`));
        return;
      }
      if (code) {
        res.end("<h2>Auth successful! You can close this tab.</h2>");
        server.close();
        resolve(code);
      }
    });
    server.listen(PORT, () =>
      console.log(`Waiting for OAuth callback on http://localhost:${PORT} ...`)
    );
  });

  // Exchange code for tokens
  const { tokens } = await oauth2.getToken(code);
  oauth2.setCredentials(tokens);

  // Save token.json to project root (same place Python watchers use it)
  writeFileSync(TOKEN_FILE, JSON.stringify(tokens, null, 2), "utf8");
  console.log(`\n✓ token.json saved to: ${TOKEN_FILE}`);
  console.log("✓ Setup complete — MCP server will now work without re-auth.\n");
}

main().catch((err) => {
  console.error("Auth failed:", err.message);
  process.exit(1);
});
