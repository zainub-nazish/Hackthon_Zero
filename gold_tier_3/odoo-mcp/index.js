/**
 * odoo-mcp — Gold Tier Odoo 17 Community MCP Server
 *
 * Connects to a local Odoo instance via JSON-RPC 2.0.
 * All operations require a valid session (authenticated via uid + password).
 *
 * Environment variables (set in .env or shell):
 *   ODOO_URL       — http://localhost:8069 (default)
 *   ODOO_DB        — odoo database name (default: odoo)
 *   ODOO_USER      — admin user login (default: admin)
 *   ODOO_PASSWORD  — admin password (default: gold_admin_2024)
 *
 * Tools exposed:
 *   create_customer       — create a res.partner record
 *   get_customers         — search customers by name/email
 *   create_invoice        — create account.move (customer invoice)
 *   get_invoices          — list invoices with status filter
 *   mark_invoice_paid     — register payment on an invoice
 *   create_task           — create project.task
 *   get_tasks             — list open tasks
 *   create_sale_order     — create sale.order
 *   get_accounting_summary — AR / AP / cash / overdue summary
 *   run_weekly_audit      — generate a full accounting audit snapshot
 *
 * Protocol: Model Context Protocol v1 (stdio transport)
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
const ODOO_URL  = process.env.ODOO_URL      ?? "http://localhost:8069";
const ODOO_DB   = process.env.ODOO_DB       ?? "odoo";
const ODOO_USER = process.env.ODOO_USER     ?? "admin";
const ODOO_PASS = process.env.ODOO_PASSWORD ?? "gold_admin_2024";

// ---------------------------------------------------------------------------
// Odoo JSON-RPC client
// ---------------------------------------------------------------------------

let _uid = null;

async function rpc(path, method, args = [], kwargs = {}) {
  const url = `${ODOO_URL}${path}`;
  const body = JSON.stringify({
    jsonrpc: "2.0",
    method:  "call",
    id:      Date.now(),
    params:  { method, args, kwargs },
  });

  const res = await fetch(url, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  const data = await res.json();
  if (data.error) throw new Error(JSON.stringify(data.error));
  return data.result;
}

async function getUid() {
  if (_uid) return _uid;
  _uid = await rpc("/web/dataset/call_kw", "authenticate", [
    ODOO_DB, ODOO_USER, ODOO_PASS, {}
  ]);
  if (!_uid) throw new Error("Odoo authentication failed — check ODOO_USER / ODOO_PASSWORD");
  log(`Authenticated as uid=${_uid}`);
  return _uid;
}

async function execute(model, method, args = [], kwargs = {}) {
  const uid = await getUid();
  return rpc("/web/dataset/call_kw", method, [ODOO_DB, uid, ODOO_PASS, model, method, ...args], kwargs);
}

async function searchRead(model, domain, fields, limit = 100, order = "id desc") {
  return execute(model, "search_read", [domain], { fields, limit, order });
}

async function create(model, values) {
  return execute(model, "create", [values]);
}

async function write(model, ids, values) {
  return execute(model, "write", [ids, values]);
}

async function callOdoo(model, method, args, kwargs) {
  return execute(model, method, args, kwargs);
}

// ---------------------------------------------------------------------------
// Tool implementations
// ---------------------------------------------------------------------------

async function createCustomer({ name, email, phone, company_name, street, city, country_code }) {
  const vals = { name, customer_rank: 1 };
  if (email)        vals.email        = email;
  if (phone)        vals.phone        = phone;
  if (company_name) vals.company_name = company_name;
  if (street)       vals.street       = street;
  if (city)         vals.city         = city;
  if (country_code) {
    const countries = await searchRead("res.country", [["code", "=", country_code.toUpperCase()]], ["id"], 1);
    if (countries.length) vals.country_id = countries[0].id;
  }
  const id = await create("res.partner", vals);
  return `Customer created: ${name} (ID: ${id})`;
}

async function getCustomers({ query, limit = 20 }) {
  const domain = query
    ? ["|", ["name", "ilike", query], ["email", "ilike", query]]
    : [["customer_rank", ">", 0]];
  const records = await searchRead("res.partner", domain,
    ["name", "email", "phone", "city", "customer_rank"], limit);
  if (!records.length) return "No customers found.";
  return records.map(r =>
    `[${r.id}] ${r.name} | ${r.email || "–"} | ${r.phone || "–"} | ${r.city || "–"}`
  ).join("\n");
}

async function createInvoice({ customer_id, customer_name, lines, due_date, note }) {
  let partner_id = customer_id;
  if (!partner_id && customer_name) {
    const res = await searchRead("res.partner", [["name", "ilike", customer_name]], ["id"], 1);
    if (!res.length) throw new Error(`Customer not found: ${customer_name}`);
    partner_id = res[0].id;
  }
  if (!partner_id) throw new Error("Provide customer_id or customer_name");

  const invoice_lines = (lines || []).map(l => [0, 0, {
    name:          l.description || "Service",
    quantity:      l.quantity    || 1,
    price_unit:    l.unit_price  || 0,
    account_id:    l.account_id  || false,
  }]);

  const vals = {
    move_type:           "out_invoice",
    partner_id,
    invoice_date:        new Date().toISOString().split("T")[0],
    invoice_date_due:    due_date || null,
    narration:           note || "",
    invoice_line_ids:    invoice_lines,
  };

  const id = await create("account.move", vals);
  return `Invoice created (ID: ${id}) for partner_id=${partner_id}. Open Odoo to review and confirm.`;
}

async function getInvoices({ state = "all", limit = 20 }) {
  const domain = [["move_type", "=", "out_invoice"]];
  if (state !== "all") domain.push(["payment_state", "=", state]);
  const records = await searchRead("account.move", domain,
    ["name", "partner_id", "amount_total", "amount_residual", "invoice_date_due", "payment_state", "state"],
    limit);
  if (!records.length) return "No invoices found.";
  return records.map(r =>
    `[${r.id}] ${r.name} | ${r.partner_id[1]} | Total: ${r.amount_total} | Due: ${r.amount_residual} | State: ${r.payment_state} | Date due: ${r.invoice_date_due || "–"}`
  ).join("\n");
}

async function markInvoicePaid({ invoice_id, payment_date, journal_name }) {
  const invoices = await searchRead("account.move", [["id", "=", invoice_id]], ["state", "payment_state"], 1);
  if (!invoices.length) throw new Error(`Invoice ${invoice_id} not found`);
  if (invoices[0].payment_state === "paid") return `Invoice ${invoice_id} is already paid.`;

  let journal_id = false;
  if (journal_name) {
    const journals = await searchRead("account.journal", [["name", "ilike", journal_name]], ["id"], 1);
    if (journals.length) journal_id = journals[0].id;
  }
  if (!journal_id) {
    const banks = await searchRead("account.journal", [["type", "in", ["bank", "cash"]]], ["id"], 1);
    if (banks.length) journal_id = banks[0].id;
  }

  const payment_vals = {
    payment_type:    "inbound",
    partner_type:    "customer",
    journal_id,
    payment_date:    payment_date || new Date().toISOString().split("T")[0],
    reconciled_invoice_ids: [[4, invoice_id]],
  };

  await callOdoo("account.move", "action_register_payment", [[invoice_id]], {});
  return `Payment registered for invoice ${invoice_id}.`;
}

async function createTask({ name, project_name, description, assignee_name, deadline }) {
  let project_id = false;
  if (project_name) {
    const projs = await searchRead("project.project", [["name", "ilike", project_name]], ["id"], 1);
    if (projs.length) project_id = projs[0].id;
    else {
      project_id = await create("project.project", { name: project_name });
    }
  }

  let user_id = false;
  if (assignee_name) {
    const users = await searchRead("res.users", [["name", "ilike", assignee_name]], ["id"], 1);
    if (users.length) user_id = users[0].id;
  }

  const vals = { name };
  if (project_id)   vals.project_id   = project_id;
  if (description)  vals.description  = description;
  if (user_id)      vals.user_ids     = [[4, user_id]];
  if (deadline)     vals.date_deadline = deadline;

  const id = await create("project.task", vals);
  return `Task created: "${name}" (ID: ${id})${project_name ? ` in project "${project_name}"` : ""}`;
}

async function getTasks({ project_name, state = "open", limit = 20 }) {
  const domain = [["stage_id.fold", "=", state !== "open"]];
  if (project_name) domain.push(["project_id.name", "ilike", project_name]);
  const records = await searchRead("project.task", domain,
    ["name", "project_id", "user_ids", "date_deadline", "stage_id"], limit);
  if (!records.length) return "No tasks found.";
  return records.map(r =>
    `[${r.id}] ${r.name} | Project: ${r.project_id ? r.project_id[1] : "–"} | Stage: ${r.stage_id[1]} | Due: ${r.date_deadline || "–"}`
  ).join("\n");
}

async function createSaleOrder({ customer_id, customer_name, lines, note }) {
  let partner_id = customer_id;
  if (!partner_id && customer_name) {
    const res = await searchRead("res.partner", [["name", "ilike", customer_name]], ["id"], 1);
    if (!res.length) throw new Error(`Customer not found: ${customer_name}`);
    partner_id = res[0].id;
  }

  const order_lines = (lines || []).map(l => [0, 0, {
    name:         l.description || "Service",
    product_uom_qty: l.quantity || 1,
    price_unit:   l.unit_price  || 0,
  }]);

  const id = await create("sale.order", {
    partner_id,
    note:          note || "",
    order_line:    order_lines,
  });
  return `Sale order created (ID: ${id}). Open Odoo to confirm.`;
}

async function getAccountingSummary() {
  const today = new Date().toISOString().split("T")[0];

  const [ar, overdue, ap, drafts] = await Promise.all([
    // Accounts Receivable — confirmed unpaid customer invoices
    searchRead("account.move",
      [["move_type","=","out_invoice"],["state","=","posted"],["payment_state","!=","paid"]],
      ["amount_residual"], 500),
    // Overdue invoices
    searchRead("account.move",
      [["move_type","=","out_invoice"],["state","=","posted"],["payment_state","!=","paid"],["invoice_date_due","<",today]],
      ["amount_residual","partner_id","invoice_date_due"], 100),
    // Accounts Payable — confirmed unpaid vendor bills
    searchRead("account.move",
      [["move_type","=","in_invoice"],["state","=","posted"],["payment_state","!=","paid"]],
      ["amount_residual"], 500),
    // Draft invoices
    searchRead("account.move",
      [["move_type","=","out_invoice"],["state","=","draft"]],
      ["amount_total"], 500),
  ]);

  const totalAR      = ar.reduce((s,r)     => s + (r.amount_residual || 0), 0);
  const totalOverdue = overdue.reduce((s,r) => s + (r.amount_residual || 0), 0);
  const totalAP      = ap.reduce((s,r)     => s + (r.amount_residual || 0), 0);
  const totalDraft   = drafts.reduce((s,r) => s + (r.amount_total    || 0), 0);

  const overdueList = overdue.slice(0, 5).map(r =>
    `  • ${r.partner_id[1]}: ${r.amount_residual.toFixed(2)} (due ${r.invoice_date_due})`
  ).join("\n");

  return [
    `=== Accounting Summary (as of ${today}) ===`,
    `Accounts Receivable (unpaid):  ${totalAR.toFixed(2)}`,
    `  Of which OVERDUE:            ${totalOverdue.toFixed(2)} (${overdue.length} invoices)`,
    overdueList ? `  Top overdue:\n${overdueList}` : "",
    `Accounts Payable (unpaid):     ${totalAP.toFixed(2)}`,
    `Draft Invoices (not sent):     ${totalDraft.toFixed(2)} (${drafts.length})`,
  ].filter(Boolean).join("\n");
}

async function runWeeklyAudit() {
  const today = new Date();
  const weekAgo = new Date(today - 7 * 86400000).toISOString().split("T")[0];
  const todayStr = today.toISOString().split("T")[0];

  const [newInvoices, paidThisWeek, newTasks, newCustomers, summary] = await Promise.all([
    searchRead("account.move",
      [["move_type","=","out_invoice"],["invoice_date",">=",weekAgo]],
      ["name","partner_id","amount_total","state"], 50),
    searchRead("account.move",
      [["move_type","=","out_invoice"],["payment_state","=","paid"],["invoice_date_due",">=",weekAgo]],
      ["name","partner_id","amount_total"], 50),
    searchRead("project.task",
      [["create_date",">=",weekAgo]],
      ["name","project_id","stage_id"], 50),
    searchRead("res.partner",
      [["customer_rank",">",0],["create_date",">=",weekAgo]],
      ["name","email"], 50),
    getAccountingSummary(),
  ]);

  const revenueCollected = paidThisWeek.reduce((s,r) => s + r.amount_total, 0);
  const invoicedTotal    = newInvoices.reduce((s,r) => s + r.amount_total, 0);

  return [
    `=== WEEKLY AUDIT REPORT (${weekAgo} → ${todayStr}) ===`,
    ``,
    `REVENUE`,
    `  Invoiced this week:   ${invoicedTotal.toFixed(2)} (${newInvoices.length} invoices)`,
    `  Collected this week:  ${revenueCollected.toFixed(2)} (${paidThisWeek.length} payments)`,
    ``,
    `OPERATIONS`,
    `  New tasks created:    ${newTasks.length}`,
    `  New customers added:  ${newCustomers.length}`,
    ``,
    summary,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Tool registry
// ---------------------------------------------------------------------------

const TOOLS = [
  {
    name: "create_customer",
    description: "Create a new customer in Odoo CRM.",
    inputSchema: {
      type: "object",
      properties: {
        name:         { type: "string", description: "Full name or company name" },
        email:        { type: "string" },
        phone:        { type: "string" },
        company_name: { type: "string" },
        street:       { type: "string" },
        city:         { type: "string" },
        country_code: { type: "string", description: "ISO 2-letter code e.g. PK, US" },
      },
      required: ["name"],
    },
  },
  {
    name: "get_customers",
    description: "Search customers by name or email.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        limit: { type: "number" },
      },
    },
  },
  {
    name: "create_invoice",
    description: "Create a customer invoice in Odoo.",
    inputSchema: {
      type: "object",
      properties: {
        customer_id:   { type: "number" },
        customer_name: { type: "string" },
        lines: {
          type: "array",
          items: {
            type: "object",
            properties: {
              description: { type: "string" },
              quantity:    { type: "number" },
              unit_price:  { type: "number" },
            },
          },
        },
        due_date: { type: "string", description: "YYYY-MM-DD" },
        note:     { type: "string" },
      },
    },
  },
  {
    name: "get_invoices",
    description: "List customer invoices. state: all | not_paid | paid | partial",
    inputSchema: {
      type: "object",
      properties: {
        state: { type: "string", enum: ["all", "not_paid", "paid", "partial", "in_payment"] },
        limit: { type: "number" },
      },
    },
  },
  {
    name: "mark_invoice_paid",
    description: "Register payment on a customer invoice.",
    inputSchema: {
      type: "object",
      properties: {
        invoice_id:   { type: "number", description: "Odoo invoice ID" },
        payment_date: { type: "string", description: "YYYY-MM-DD (defaults to today)" },
        journal_name: { type: "string", description: "e.g. Bank, Cash" },
      },
      required: ["invoice_id"],
    },
  },
  {
    name: "create_task",
    description: "Create a task in Odoo Project.",
    inputSchema: {
      type: "object",
      properties: {
        name:          { type: "string" },
        project_name:  { type: "string" },
        description:   { type: "string" },
        assignee_name: { type: "string" },
        deadline:      { type: "string", description: "YYYY-MM-DD" },
      },
      required: ["name"],
    },
  },
  {
    name: "get_tasks",
    description: "List project tasks.",
    inputSchema: {
      type: "object",
      properties: {
        project_name: { type: "string" },
        state:        { type: "string", enum: ["open", "closed"] },
        limit:        { type: "number" },
      },
    },
  },
  {
    name: "create_sale_order",
    description: "Create a sale order in Odoo.",
    inputSchema: {
      type: "object",
      properties: {
        customer_name: { type: "string" },
        customer_id:   { type: "number" },
        lines: {
          type: "array",
          items: {
            type: "object",
            properties: {
              description: { type: "string" },
              quantity:    { type: "number" },
              unit_price:  { type: "number" },
            },
          },
        },
        note: { type: "string" },
      },
    },
  },
  {
    name: "get_accounting_summary",
    description: "Get AR, AP, overdue invoices, and draft invoice totals.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "run_weekly_audit",
    description: "Generate a weekly business and accounting audit report.",
    inputSchema: { type: "object", properties: {} },
  },
];

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "odoo-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;

  try {
    let result;
    switch (name) {
      case "create_customer":        result = await createCustomer(args);        break;
      case "get_customers":          result = await getCustomers(args);          break;
      case "create_invoice":         result = await createInvoice(args);         break;
      case "get_invoices":           result = await getInvoices(args);           break;
      case "mark_invoice_paid":      result = await markInvoicePaid(args);       break;
      case "create_task":            result = await createTask(args);            break;
      case "get_tasks":              result = await getTasks(args);              break;
      case "create_sale_order":      result = await createSaleOrder(args);       break;
      case "get_accounting_summary": result = await getAccountingSummary();      break;
      case "run_weekly_audit":       result = await runWeeklyAudit();            break;
      default: return err(`Unknown tool: ${name}`);
    }
    return ok(typeof result === "string" ? result : JSON.stringify(result, null, 2));
  } catch (e) {
    return err(`${name} failed: ${e.message}`);
  }
});

function ok(text)  { return { content: [{ type: "text", text }] }; }
function err(text) { return { content: [{ type: "text", text }], isError: true }; }
function log(...a) { console.error("[odoo-mcp]", ...a); }

const transport = new StdioServerTransport();
await server.connect(transport);
log(`Server ready — connected to Odoo at ${ODOO_URL} (db: ${ODOO_DB})`);
