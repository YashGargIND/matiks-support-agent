import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { summarize, assignmentGroups } from "../lib/summarize";
const config = {
  modules: [{ id: "other", name: "Other", keywords: [], destination: "" }],
};
const tickets = [
  {
    id: "real-clickup-8abcdefgh",
    title: "Fictional feed request",
    body: "Incidental ID8other inside untrusted text.",
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
const output = (
  assignments: Record<string, string>,
  summary = "Requested product improvements.",
) =>
  Response.json({
    choices: [
      {
        message: {
          content: JSON.stringify({
            assignments,
            summaries: { other: summary },
          }),
        },
      },
    ],
  });
test("strict required-property assignments map each report once; missing assignment gets one specific repair", async () => {
  let calls = 0;
  const fake = (async (_url, init) => {
    calls++;
    const body = JSON.parse(String(init?.body));
    const input = JSON.parse(body.messages[1].content);
    const schema = body.response_format.json_schema.schema;
    assert.deepEqual(
      input.reports.map((report: { id: string }) => report.id),
      ["r1", "r2"],
    );
    assert.deepEqual(schema.properties.assignments.required, ["r1", "r2"]);
    assert.deepEqual(schema.properties.assignments.properties.r1.enum, [
      "other",
    ]);
    assert.equal(schema.properties.assignments.additionalProperties, false);
    assert.deepEqual(schema.properties.summaries.required, ["other"]);
    assert.ok(!JSON.stringify(body).includes("real-clickup-"));
    if (calls === 1) return output({ r1: "other" });
    assert.match(body.messages[0].content, /omitted assignments/);
    return output({ r1: "other", r2: "other" });
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
test("unknown module fails specifically after two calls and remains retryable", async () => {
  let calls = 0;
  await assert.rejects(
    summarize(tickets, config, 2, (async () => {
      calls++;
      return output({ r1: "invented", r2: "other" });
    }) as typeof fetch),
    /assigned a report to an unknown module.*Nothing was sent/,
  );
  assert.equal(calls, 2);
  assert.equal(
    (await readdir(directory)).filter((name) => name.startsWith("run-")).length,
    0,
  );
  let retries = 0;
  const run = await summarize(tickets, config, 2, (async () => {
    retries++;
    return output({ r1: "other", r2: "other" });
  }) as typeof fetch);
  assert.equal(retries, 1);
  assert.equal(run.modelCalls, 3);
  assert.equal(run.summaries[0].ticketIds.length, 2);
});
test("800-character target is not misreported as coverage failure; reasonable longer summary passes", async () => {
  let calls = 0;
  const run = await summarize(tickets, config, 2, (async () => {
    calls++;
    return output({ r1: "other", r2: "other" }, "x".repeat(1000));
  }) as typeof fetch);
  assert.equal(calls, 1);
  assert.equal(run.summaries[0].summary.length, 1000);
});
test("over3500 characters produces specific brevity feedback and one repair", async () => {
  let calls = 0;
  const run = await summarize(tickets, config, 2, (async (_url, init) => {
    calls++;
    if (calls === 2)
      assert.match(
        JSON.parse(String(init?.body)).messages[0].content,
        /3500-character/,
      );
    return output(
      { r1: "other", r2: "other" },
      calls === 1 ? "x".repeat(3501) : "Concise improvements.",
    );
  }) as typeof fetch);
  assert.equal(calls, 2);
  assert.equal(run.summaries[0].ticketIds.length, 2);
});
test("pure decoder rejects missing refs, wrong enum, extra refs, empty used summaries with distinct errors", () => {
  const valid = {
    assignments: { r1: "other", r2: "other" },
    summaries: { other: "Requested improvements." },
  };
  assert.deepEqual(
    assignmentGroups(valid, tickets, config)[0].ticketIds,
    tickets.map((t) => t.id),
  );
  assert.throws(
    () =>
      assignmentGroups(
        { ...valid, assignments: { r1: "other" } },
        tickets,
        config,
      ),
    /omitted assignments/,
  );
  assert.throws(
    () =>
      assignmentGroups(
        { ...valid, assignments: { r1: "wrong", r2: "other" } },
        tickets,
        config,
      ),
    /unknown module/,
  );
  assert.throws(
    () =>
      assignmentGroups(
        { ...valid, assignments: { ...valid.assignments, r3: "other" } },
        tickets,
        config,
      ),
    /unknown report reference/,
  );
  assert.throws(
    () =>
      assignmentGroups({ ...valid, summaries: { other: "" } }, tickets, config),
    /used module summary empty/,
  );
  assert.throws(
    () => assignmentGroups({ ...valid, summaries: {} }, tickets, config),
    /omitted a configured module summary/,
  );
});
test("unused configured modules may have empty summaries while used groups contain every real ID", () => {
  const modules = {
    modules: [
      ...config.modules,
      { id: "feed", name: "Feed", keywords: [], destination: "" },
    ],
  };
  const groups = assignmentGroups(
    {
      assignments: { r1: "other", r2: "other" },
      summaries: { other: "Ideas.", feed: "" },
    },
    tickets,
    modules,
  );
  assert.equal(groups.length, 1);
  assert.deepEqual(
    groups[0].ticketIds,
    tickets.map((t) => t.id),
  );
});
