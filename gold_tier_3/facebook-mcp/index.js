/**
 * facebook-mcp — Gold Tier Facebook + Instagram Graph API MCP Server
 *
 * Facebook and Instagram share the same Graph API app credentials.
 * Instagram requires a Professional (Business/Creator) account connected to a Facebook Page.
 *
 * Environment variables:
 *   FB_PAGE_ACCESS_TOKEN   — Long-lived Page Access Token (from Graph API Explorer)
 *   FB_PAGE_ID             — Facebook Page numeric ID
 *   IG_ACCOUNT_ID          — Instagram Business Account ID (from FB Graph API)
 *   FB_APP_ID              — Facebook App ID (optional, for token refresh)
 *   FB_APP_SECRET          — Facebook App Secret (optional, for token refresh)
 *
 * Tools:
 *   post_to_facebook        — Post text/link to Facebook Page feed
 *   get_page_messages       — Get recent unread messages from Page inbox
 *   reply_to_message        — Reply to a Facebook Page conversation
 *   get_page_summary        — Page insights: reach, engagement, follower count
 *   post_to_instagram       — Post image/caption to Instagram Business account
 *   get_instagram_comments  — Get recent comments on IG posts
 *   reply_to_ig_comment     — Reply to an Instagram comment
 *   get_social_summary      — Combined FB + IG weekly summary
 */

import { Server }               from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const TOKEN      = process.env.FB_PAGE_ACCESS_TOKEN ?? "";
const PAGE_ID    = process.env.FB_PAGE_ID           ?? "";
const IG_ID      = process.env.IG_ACCOUNT_ID        ?? "";
const GRAPH_VER  = "v19.0";
const BASE       = `https://graph.facebook.com/${GRAPH_VER}`;

// ---------------------------------------------------------------------------
// Graph API helper
// ---------------------------------------------------------------------------

async function graph(path, method = "GET", body = null) {
  const sep = path.includes("?") ? "&" : "?";
  const url = `${BASE}${path}${sep}access_token=${TOKEN}`;

  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);

  const res  = await fetch(url, opts);
  const data = await res.json();

  if (data.error) throw new Error(`Graph API: ${data.error.message} (code ${data.error.code})`);
  return data;
}

// ---------------------------------------------------------------------------
// Facebook tools
// ---------------------------------------------------------------------------

async function postToFacebook({ message, link, published = true }) {
  if (!PAGE_ID) throw new Error("FB_PAGE_ID not set");
  if (!TOKEN)   throw new Error("FB_PAGE_ACCESS_TOKEN not set");

  const body = { message, published };
  if (link) body.link = link;

  const res = await graph(`/${PAGE_ID}/feed`, "POST", body);
  return `Facebook post published!\nPost ID: ${res.id}\nMessage: ${message.substring(0, 80)}…`;
}

async function getPageMessages({ limit = 10 }) {
  if (!PAGE_ID) throw new Error("FB_PAGE_ID not set");

  const data = await graph(
    `/${PAGE_ID}/conversations?fields=participants,messages{message,created_time,from}&limit=${limit}`
  );

  const convos = data.data || [];
  if (!convos.length) return "No conversations found in Page inbox.";

  return convos.slice(0, limit).map(c => {
    const msgs = c.messages?.data || [];
    const latest = msgs[0];
    const participants = (c.participants?.data || []).map(p => p.name).join(", ");
    return [
      `Conversation with: ${participants}`,
      latest ? `  Latest: "${latest.message?.substring(0, 100)}" at ${latest.created_time}` : "  (no messages)",
      `  Thread ID: ${c.id}`,
    ].join("\n");
  }).join("\n\n");
}

async function replyToMessage({ conversation_id, message }) {
  if (!PAGE_ID) throw new Error("FB_PAGE_ID not set");
  const res = await graph(`/${conversation_id}/messages`, "POST", { message });
  return `Reply sent! Message ID: ${res.message_id || res.id}`;
}

async function getPageSummary() {
  if (!PAGE_ID) throw new Error("FB_PAGE_ID not set");

  const since = Math.floor((Date.now() - 7 * 86400000) / 1000);
  const until = Math.floor(Date.now() / 1000);

  const [pageData, insights] = await Promise.all([
    graph(`/${PAGE_ID}?fields=name,fan_count,followers_count`),
    graph(`/${PAGE_ID}/insights?metric=page_impressions,page_engaged_users,page_post_engagements&since=${since}&until=${until}&period=week`)
      .catch(() => ({ data: [] })),
  ]);

  const metrics = {};
  for (const item of insights.data || []) {
    const val = item.values?.slice(-1)[0]?.value;
    metrics[item.name] = val ?? "N/A";
  }

  return [
    `=== Facebook Page Summary ===`,
    `Page:           ${pageData.name}`,
    `Fans/Likes:     ${pageData.fan_count ?? "N/A"}`,
    `Followers:      ${pageData.followers_count ?? "N/A"}`,
    `Weekly Reach:   ${metrics.page_impressions ?? "N/A"}`,
    `Engaged Users:  ${metrics.page_engaged_users ?? "N/A"}`,
    `Post Engages:   ${metrics.page_post_engagements ?? "N/A"}`,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Instagram tools
// ---------------------------------------------------------------------------

async function postToInstagram({ image_url, caption }) {
  if (!IG_ID) throw new Error("IG_ACCOUNT_ID not set — set in .env");
  if (!image_url) throw new Error("image_url is required for Instagram posts");

  // Step 1: Create media container
  const container = await graph(`/${IG_ID}/media`, "POST", {
    image_url,
    caption: caption || "",
  });

  if (!container.id) throw new Error("Failed to create Instagram media container");

  // Step 2: Publish the container
  const pub = await graph(`/${IG_ID}/media_publish`, "POST", {
    creation_id: container.id,
  });

  return `Instagram post published!\nMedia ID: ${pub.id}\nCaption: ${(caption || "").substring(0, 80)}`;
}

async function getInstagramComments({ limit = 20 }) {
  if (!IG_ID) throw new Error("IG_ACCOUNT_ID not set");

  const posts = await graph(`/${IG_ID}/media?fields=id,caption,timestamp&limit=5`);
  if (!posts.data?.length) return "No Instagram posts found.";

  const results = [];
  for (const post of posts.data.slice(0, 3)) {
    const comments = await graph(`/${post.id}/comments?fields=text,username,timestamp&limit=${limit}`)
      .catch(() => ({ data: [] }));
    if (comments.data?.length) {
      results.push(`Post: "${(post.caption || "").substring(0, 60)}" (${post.timestamp})`);
      for (const c of comments.data.slice(0, 5)) {
        results.push(`  @${c.username}: ${c.text} — ${c.timestamp}`);
      }
    }
  }

  return results.length ? results.join("\n") : "No comments found on recent posts.";
}

async function replyToIgComment({ comment_id, message }) {
  const res = await graph(`/${comment_id}/replies`, "POST", { message });
  return `Instagram comment reply sent! ID: ${res.id}`;
}

async function getSocialSummary() {
  const [fb, ig] = await Promise.all([
    getPageSummary().catch(e => `Facebook summary failed: ${e.message}`),
    IG_ID
      ? graph(`/${IG_ID}?fields=name,biography,followers_count,media_count`)
          .then(d => [
            `=== Instagram Summary ===`,
            `Account:    ${d.name}`,
            `Followers:  ${d.followers_count}`,
            `Total Posts:${d.media_count}`,
          ].join("\n"))
          .catch(e => `Instagram summary failed: ${e.message}`)
      : "Instagram: IG_ACCOUNT_ID not configured.",
  ]);

  return `${fb}\n\n${ig}`;
}

// ---------------------------------------------------------------------------
// Tool registry
// ---------------------------------------------------------------------------

const TOOLS = [
  {
    name: "post_to_facebook",
    description: "Post a message to your Facebook Business Page feed.",
    inputSchema: {
      type: "object",
      properties: {
        message:   { type: "string", description: "Post text content" },
        link:      { type: "string", description: "Optional URL to attach" },
        published: { type: "boolean", description: "Publish immediately (default true)" },
      },
      required: ["message"],
    },
  },
  {
    name: "get_page_messages",
    description: "Get recent conversations from your Facebook Page inbox.",
    inputSchema: {
      type: "object",
      properties: { limit: { type: "number", description: "Max conversations (default 10)" } },
    },
  },
  {
    name: "reply_to_message",
    description: "Reply to a Facebook Page conversation thread.",
    inputSchema: {
      type: "object",
      properties: {
        conversation_id: { type: "string" },
        message:         { type: "string" },
      },
      required: ["conversation_id", "message"],
    },
  },
  {
    name: "get_page_summary",
    description: "Get Facebook Page insights: fans, followers, weekly reach, engagement.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "post_to_instagram",
    description: "Post an image with caption to your Instagram Business account.",
    inputSchema: {
      type: "object",
      properties: {
        image_url: { type: "string", description: "Public HTTPS URL of the image" },
        caption:   { type: "string" },
      },
      required: ["image_url"],
    },
  },
  {
    name: "get_instagram_comments",
    description: "Get recent comments on your Instagram posts.",
    inputSchema: {
      type: "object",
      properties: { limit: { type: "number" } },
    },
  },
  {
    name: "reply_to_ig_comment",
    description: "Reply to an Instagram comment.",
    inputSchema: {
      type: "object",
      properties: {
        comment_id: { type: "string" },
        message:    { type: "string" },
      },
      required: ["comment_id", "message"],
    },
  },
  {
    name: "get_social_summary",
    description: "Get combined Facebook + Instagram weekly analytics summary.",
    inputSchema: { type: "object", properties: {} },
  },
];

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "facebook-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;
  try {
    let result;
    switch (name) {
      case "post_to_facebook":       result = await postToFacebook(args);       break;
      case "get_page_messages":      result = await getPageMessages(args);      break;
      case "reply_to_message":       result = await replyToMessage(args);       break;
      case "get_page_summary":       result = await getPageSummary();           break;
      case "post_to_instagram":      result = await postToInstagram(args);      break;
      case "get_instagram_comments": result = await getInstagramComments(args); break;
      case "reply_to_ig_comment":    result = await replyToIgComment(args);     break;
      case "get_social_summary":     result = await getSocialSummary();         break;
      default: return err(`Unknown tool: ${name}`);
    }
    return ok(typeof result === "string" ? result : JSON.stringify(result, null, 2));
  } catch (e) {
    return err(`${name} failed: ${e.message}`);
  }
});

function ok(text)  { return { content: [{ type: "text", text }] }; }
function err(text) { return { content: [{ type: "text", text }], isError: true }; }
function log(...a) { console.error("[facebook-mcp]", ...a); }

const transport = new StdioServerTransport();
await server.connect(transport);
log("Server ready — Facebook + Instagram Graph API tools available.");
