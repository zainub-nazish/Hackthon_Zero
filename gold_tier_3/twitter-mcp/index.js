/**
 * twitter-mcp — Gold Tier Twitter (X) v2 API MCP Server
 *
 * Uses Twitter API v2 with OAuth 2.0 Bearer Token (read) and
 * OAuth 1.0a User Context (write — tweets, replies).
 *
 * Environment variables:
 *   TWITTER_BEARER_TOKEN       — App-only Bearer Token (read access)
 *   TWITTER_API_KEY            — OAuth 1.0a API Key (Consumer Key)
 *   TWITTER_API_SECRET         — OAuth 1.0a API Secret (Consumer Secret)
 *   TWITTER_ACCESS_TOKEN       — OAuth 1.0a Access Token (user write)
 *   TWITTER_ACCESS_TOKEN_SECRET— OAuth 1.0a Access Token Secret
 *   TWITTER_USER_ID            — Your Twitter numeric user ID
 *
 * Tools:
 *   post_tweet         — Post a new tweet
 *   reply_to_tweet     — Reply to an existing tweet
 *   get_mentions       — Get recent @mentions of your account
 *   get_home_timeline  — Get recent tweets from home timeline
 *   get_twitter_summary— Weekly engagement summary
 *   delete_tweet       — Delete a tweet by ID
 */

import { Server }               from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import crypto from "crypto";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const BEARER       = process.env.TWITTER_BEARER_TOKEN         ?? "";
const API_KEY      = process.env.TWITTER_API_KEY              ?? "";
const API_SECRET   = process.env.TWITTER_API_SECRET           ?? "";
const ACCESS_TOK   = process.env.TWITTER_ACCESS_TOKEN         ?? "";
const ACCESS_SEC   = process.env.TWITTER_ACCESS_TOKEN_SECRET  ?? "";
const USER_ID      = process.env.TWITTER_USER_ID              ?? "";

const BASE_V2 = "https://api.twitter.com/2";

// ---------------------------------------------------------------------------
// OAuth 1.0a signer (needed for write operations)
// ---------------------------------------------------------------------------

function oauthSign(method, url, params, body = {}) {
  const oauthParams = {
    oauth_consumer_key:     API_KEY,
    oauth_nonce:            crypto.randomBytes(16).toString("hex"),
    oauth_signature_method: "HMAC-SHA1",
    oauth_timestamp:        Math.floor(Date.now() / 1000).toString(),
    oauth_token:            ACCESS_TOK,
    oauth_version:          "1.0",
  };

  const allParams = { ...params, ...oauthParams };
  const sortedKeys = Object.keys(allParams).sort();
  const paramStr = sortedKeys
    .map(k => `${pct(k)}=${pct(allParams[k])}`)
    .join("&");

  const baseStr = [method.toUpperCase(), pct(url), pct(paramStr)].join("&");
  const sigKey  = `${pct(API_SECRET)}&${pct(ACCESS_SEC)}`;
  const sig     = crypto.createHmac("sha1", sigKey).update(baseStr).digest("base64");

  oauthParams.oauth_signature = sig;

  const authHeader = "OAuth " + Object.keys(oauthParams)
    .sort()
    .map(k => `${pct(k)}="${pct(oauthParams[k])}"`)
    .join(", ");

  return authHeader;
}

function pct(s) {
  return encodeURIComponent(String(s));
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function twitterGet(path, params = {}) {
  if (!BEARER) throw new Error("TWITTER_BEARER_TOKEN not set");
  const qs  = new URLSearchParams(params).toString();
  const url = `${BASE_V2}${path}${qs ? "?" + qs : ""}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${BEARER}` },
  });
  const data = await res.json();
  if (data.errors?.length) throw new Error(data.errors.map(e => e.detail || e.message).join("; "));
  return data;
}

async function twitterPost(path, body) {
  if (!API_KEY) throw new Error("TWITTER_API_KEY not set — OAuth 1.0a credentials required for write ops");
  const url = `${BASE_V2}${path}`;
  const authHeader = oauthSign("POST", url, {});
  const res = await fetch(url, {
    method:  "POST",
    headers: {
      Authorization:  authHeader,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.errors?.length) throw new Error(data.errors.map(e => e.detail || e.title).join("; "));
  if (data.status >= 400) throw new Error(data.detail || data.title || "Twitter API error");
  return data;
}

async function twitterDelete(path) {
  if (!API_KEY) throw new Error("TWITTER_API_KEY not set");
  const url = `${BASE_V2}${path}`;
  const authHeader = oauthSign("DELETE", url, {});
  const res = await fetch(url, {
    method:  "DELETE",
    headers: { Authorization: authHeader },
  });
  return res.json();
}

// ---------------------------------------------------------------------------
// Tool implementations
// ---------------------------------------------------------------------------

async function postTweet({ text, reply_to_tweet_id }) {
  const body = { text };
  if (reply_to_tweet_id) body.reply = { in_reply_to_tweet_id: reply_to_tweet_id };

  const data = await twitterPost("/tweets", body);
  const tweet = data.data;
  return `Tweet posted!\nID: ${tweet.id}\nText: ${tweet.text}`;
}

async function replyToTweet({ tweet_id, text }) {
  return postTweet({ text, reply_to_tweet_id: tweet_id });
}

async function getMentions({ limit = 10, since_hours = 24 }) {
  if (!USER_ID) throw new Error("TWITTER_USER_ID not set");

  const startTime = new Date(Date.now() - since_hours * 3600000).toISOString();
  const data = await twitterGet(`/users/${USER_ID}/mentions`, {
    max_results: Math.min(limit, 100),
    start_time:  startTime,
    "tweet.fields": "created_at,author_id,text",
    expansions:  "author_id",
    "user.fields": "name,username",
  });

  const tweets = data.data || [];
  if (!tweets.length) return `No mentions found in the last ${since_hours} hours.`;

  const users = {};
  for (const u of data.includes?.users || []) users[u.id] = u;

  return tweets.map(t => {
    const author = users[t.author_id];
    return `@${author?.username || t.author_id}: ${t.text}\n  ID: ${t.id} | ${t.created_at}`;
  }).join("\n\n");
}

async function getHomeTimeline({ limit = 10 }) {
  if (!USER_ID) throw new Error("TWITTER_USER_ID not set");

  const data = await twitterGet(`/users/${USER_ID}/timelines/reverse_chronological`, {
    max_results: Math.min(limit, 100),
    "tweet.fields": "created_at,author_id,public_metrics",
    expansions:  "author_id",
    "user.fields": "name,username",
  });

  const tweets = data.data || [];
  if (!tweets.length) return "No tweets in timeline.";

  const users = {};
  for (const u of data.includes?.users || []) users[u.id] = u;

  return tweets.map(t => {
    const author = users[t.author_id];
    const m = t.public_metrics || {};
    return `@${author?.username || "?"}: ${t.text.substring(0, 100)}\n  ❤️ ${m.like_count} | 🔁 ${m.retweet_count} | 💬 ${m.reply_count}`;
  }).join("\n\n");
}

async function getTwitterSummary() {
  if (!USER_ID) throw new Error("TWITTER_USER_ID not set");

  const [userRes, mentions] = await Promise.all([
    twitterGet(`/users/${USER_ID}`, {
      "user.fields": "name,username,public_metrics,description",
    }),
    getMentions({ limit: 5, since_hours: 168 }).catch(e => `Mentions error: ${e.message}`),
  ]);

  const u = userRes.data;
  const m = u.public_metrics || {};

  return [
    `=== Twitter (X) Summary ===`,
    `Account:    @${u.username} (${u.name})`,
    `Followers:  ${m.followers_count}`,
    `Following:  ${m.following_count}`,
    `Tweets:     ${m.tweet_count}`,
    ``,
    `Recent Mentions (last 7 days):`,
    mentions,
  ].join("\n");
}

async function deleteTweet({ tweet_id }) {
  const data = await twitterDelete(`/tweets/${tweet_id}`);
  const deleted = data.data?.deleted;
  return deleted ? `Tweet ${tweet_id} deleted successfully.` : `Could not delete tweet ${tweet_id}.`;
}

// ---------------------------------------------------------------------------
// Tool registry
// ---------------------------------------------------------------------------

const TOOLS = [
  {
    name: "post_tweet",
    description: "Post a new tweet to Twitter (X).",
    inputSchema: {
      type: "object",
      properties: {
        text:              { type: "string", description: "Tweet text (max 280 chars)" },
        reply_to_tweet_id: { type: "string", description: "Optional: tweet ID to reply to" },
      },
      required: ["text"],
    },
  },
  {
    name: "reply_to_tweet",
    description: "Reply to an existing tweet.",
    inputSchema: {
      type: "object",
      properties: {
        tweet_id: { type: "string" },
        text:     { type: "string" },
      },
      required: ["tweet_id", "text"],
    },
  },
  {
    name: "get_mentions",
    description: "Get recent @mentions of your account.",
    inputSchema: {
      type: "object",
      properties: {
        limit:       { type: "number" },
        since_hours: { type: "number", description: "Look back N hours (default 24)" },
      },
    },
  },
  {
    name: "get_home_timeline",
    description: "Get recent tweets from your home timeline.",
    inputSchema: {
      type: "object",
      properties: { limit: { type: "number" } },
    },
  },
  {
    name: "get_twitter_summary",
    description: "Get your Twitter profile stats and recent mentions summary.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "delete_tweet",
    description: "Delete a tweet by ID.",
    inputSchema: {
      type: "object",
      properties: { tweet_id: { type: "string" } },
      required: ["tweet_id"],
    },
  },
];

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "twitter-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;
  try {
    let result;
    switch (name) {
      case "post_tweet":          result = await postTweet(args);          break;
      case "reply_to_tweet":      result = await replyToTweet(args);       break;
      case "get_mentions":        result = await getMentions(args);        break;
      case "get_home_timeline":   result = await getHomeTimeline(args);    break;
      case "get_twitter_summary": result = await getTwitterSummary();      break;
      case "delete_tweet":        result = await deleteTweet(args);        break;
      default: return err(`Unknown tool: ${name}`);
    }
    return ok(typeof result === "string" ? result : JSON.stringify(result, null, 2));
  } catch (e) {
    return err(`${name} failed: ${e.message}`);
  }
});

function ok(text)  { return { content: [{ type: "text", text }] }; }
function err(text) { return { content: [{ type: "text", text }], isError: true }; }
function log(...a) { console.error("[twitter-mcp]", ...a); }

const transport = new StdioServerTransport();
await server.connect(transport);
log("Server ready — Twitter (X) v2 API tools available.");
