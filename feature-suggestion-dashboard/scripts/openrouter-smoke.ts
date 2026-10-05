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
    Array.from({ length: 20 }, (_, index) => {
      const ideas = [
        [
          "Hide feed posts",
          "Let me hide feed posts that are not interesting, and remember that choice.",
        ],
        [
          "Offline lessons",
          "Let me download learning lessons and practice when travelling without internet.",
        ],
        [
          "Rematch button",
          "Add a rematch button after a duel so friends can play the same game again.",
        ],
        [
          "Streak calendar",
          "Add a calendar on my profile showing historical streak progress and earned rewards.",
        ],
        [
          "Quiet notifications",
          "Let me configure notification hours and sound preferences in settings.",
        ],
      ];
      const idea = ideas[index % ideas.length];
      return {
        id: `fictional-${String(index).padStart(2, "0")}`,
        title: `Suggestion: ${idea[0]}`,
        body: `Fictional test report ${index + 1}: ${idea[1]} ${"This fictional example describes a requested product improvement, not an existing feature or a promised release. ".repeat((index % 4) + 1)}`,
        createdAt: "2026-10-05T00:00:00Z",
        status: "test",
        url: "",
      };
    }),
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
        {
          id: "gameplay",
          name: "Gameplay",
          keywords: ["duel", "rematch"],
          destination: "",
        },
        {
          id: "profile",
          name: "Profile",
          keywords: ["profile", "streak", "reward"],
          destination: "",
        },
        { id: "other", name: "Other", keywords: [], destination: "" },
      ],
    },
    20,
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
