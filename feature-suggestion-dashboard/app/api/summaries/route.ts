import { fetchSuggestions } from "@/lib/clickup";
import { getConfig } from "@/lib/storage";
import { summarize } from "@/lib/summarize";
import { sendRun } from "@/lib/slack";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export async function POST(request: Request) {
  try {
    requireLocalRequest(request);
    const body = await request.json();
    if (body.send !== false && body.send !== true)
      throw new Error("Choose preview or send.");
    if (body.send && !process.env.SLACK_BOT_TOKEN)
      throw new Error(
        "Add SLACK_BOT_TOKEN before summarizing and sending. Preview is available now.",
      );
    const config = await getConfig();
    const { tickets, fetchedTasks } = await fetchSuggestions();
    const run = await summarize(tickets, config, fetchedTasks);
    return Response.json(body.send ? await sendRun(run.id) : run);
  } catch (e) {
    return failure(e);
  }
}
