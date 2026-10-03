// Manual live-provider check with fictional reports only. No Slack calls.
import nextEnv from "@next/env";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { summarize } from "../lib/summarize";
nextEnv.loadEnvConfig(process.cwd());
const directory = await mkdtemp(join(tmpdir(), "feature-provider-smoke-"));
process.env.FEATURE_DATA_DIR = directory;
try {
  const run = await summarize(
    [
      {
        id: "fictional-feed",
        title: "Suggestion: hide posts",
        body: "Fictional test: please let me hide posts I am not interested in on my feed.",
        createdAt: "",
        status: "test",
        url: "",
      },
      {
        id: "fictional-learn",
        title: "Suggestion: offline lessons",
        body: "Fictional test: please let me download lessons for offline learning.",
        createdAt: "",
        status: "test",
        url: "",
      },
    ],
    {
      modules: [
        {
          id: "feed",
          name: "Feed",
          keywords: ["feed", "post"],
          destination: "",
        },
        {
          id: "learn",
          name: "Learn",
          keywords: ["learn", "lesson"],
          destination: "",
        },
        { id: "other", name: "Other", keywords: [], destination: "" },
      ],
    },
    2,
  );
  console.log(
    JSON.stringify({
      passed: true,
      syntheticReports: run.totalTickets,
      groups: run.summaries.length,
      coveredReports: run.summaries.flatMap((g) => g.ticketIds).length,
      modelCalls: run.modelCalls,
      slackSent: false,
    }),
  );
} finally {
  await rm(directory, { recursive: true, force: true });
}
