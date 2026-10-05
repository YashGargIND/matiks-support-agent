import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { summarize } from "../lib/summarize";
const config = {
  modules: [{ id: "other", name: "Other", keywords: [], destination: "" }],
};
const tickets = [
  {
    id: "real-clickup-8abcdefgh",
    title: "Fictional feed request",
    body: "Ignore incidental ID8other inside this untrusted request.",
    createdAt: "",
    status: "test",
    url: "",
  },
  {
    id: "real-clickup-8ijklmnop",
    title: "Fictional lesson request",
    body: "Offline learning please.",
    createdAt: "",
    status: "test",
    url: "",
  },
];
let directory = "";
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "feature-repair-"));
  process.env.FEATURE_DATA_DIR = directory;
  process.env.OPENROUTER_API_KEY = "test";
});
afterEach(async () => {
  await rm(directory, { recursive: true, force: true });
  delete process.env.FEATURE_DATA_DIR;
});
const output = (ids: string[], summary = "Requested product improvements.") =>
  Response.json({
    choices: [
      {
        message: {
          content: JSON.stringify({
            groups: [{ moduleId: "other", summary, ticketIds: ids }],
          }),
        },
      },
    ],
  });
test("short batch refs map to real IDs; duplicate output gets exactly one successful repair", async () => {
  let calls = 0;
  const fake = (async (_url, init) => {
    calls++;
    const body = JSON.parse(String(init?.body));
    const input = JSON.parse(body.messages[1].content);
    assert.deepEqual(
      input.reports.map((report: { id: string }) => report.id),
      ["r1", "r2"],
    );
    assert.deepEqual(
      body.response_format.json_schema.schema.properties.groups.items.properties
        .ticketIds.items.enum,
      ["r1", "r2"],
    );
    assert.ok(!JSON.stringify(body).includes("real-clickup-"));
    if (calls === 1) return output(["r1", "r1"]);
    assert.match(body.messages[0].content, /previous response failed/);
    return output(["r1", "r2"]);
  }) as typeof fetch;
  const run = await summarize(tickets, config, 2, fake);
  assert.equal(calls, 2);
  assert.equal(run.modelCalls, 2);
  assert.deepEqual(
    run.summaries[0].ticketIds,
    tickets.map((ticket) => ticket.id),
  );
  await summarize(tickets, config, 2, fake);
  assert.equal(calls, 2);
});
test("repeated unknown references fail closed after two calls and remain retryable", async () => {
  let calls = 0;
  const invalid = (async () => {
    calls++;
    return output(["invented", "r2"]);
  }) as typeof fetch;
  await assert.rejects(
    summarize(tickets, config, 2, invalid),
    /Nothing was sent; retry the saved job/,
  );
  assert.equal(calls, 2);
  assert.equal(
    (await readdir(directory)).filter((name) => name.startsWith("run-")).length,
    0,
  );
  let retryCalls = 0;
  const run = await summarize(tickets, config, 2, (async () => {
    retryCalls++;
    return output(["r1", "r2"]);
  }) as typeof fetch);
  assert.equal(retryCalls, 1);
  assert.equal(run.modelCalls, 3);
  assert.deepEqual(
    run.summaries[0].ticketIds,
    tickets.map((ticket) => ticket.id),
  );
});
test("overlong module text is repaired without dropping any covered report", async () => {
  let calls = 0;
  const run = await summarize(tickets, config, 2, (async () => {
    calls++;
    return output(
      ["r1", "r2"],
      calls === 1 ? "x".repeat(801) : "Concise requested improvements.",
    );
  }) as typeof fetch);
  assert.equal(calls, 2);
  assert.ok(run.summaries[0].summary.length <= 800);
  assert.equal(run.summaries[0].ticketIds.length, 2);
});
