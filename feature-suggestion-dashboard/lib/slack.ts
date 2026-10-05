import type { Run } from "./types";
import { getRun, saveRun, withRunLock } from "./storage";
async function slack(method: string, body: object, fetcher: typeof fetch) {
  const response = await fetcher(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok)
    throw new Error(
      `Slack request status is uncertain (HTTP ${response.status}). Verify Slack before retrying.`,
    );
  return response.json();
}
function escapeSlack(text: string) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
export async function sendRun(
  id: string,
  fetcher: typeof fetch = fetch,
): Promise<Run> {
  if (!process.env.SLACK_BOT_TOKEN)
    throw new Error("Configure SLACK_BOT_TOKEN in .env.local before sending.");
  return withRunLock(id, async () => {
    const run = await getRun(id);
    if (run.scope === "demo")
      throw new Error(
        "Quick demo previews cannot be sent to Slack. Use a normal all-suggestions job.",
      );
    for (const group of run.summaries) {
      const delivery = run.deliveries[group.moduleId];
      if (["sent", "unknown", "sending"].includes(delivery.state)) continue;
      if (!delivery.destination) {
        delivery.state = "unconfigured";
        delivery.error =
          "No Slack destination configured. Save routing and create a new summary.";
        continue;
      }
      const module = run.config.modules.find((m) => m.id === group.moduleId)!;
      const examples = group.ticketIds.slice(0, 10);
      const text = `*Matiks suggestions — ${escapeSlack(module.name)}*\n${group.ticketIds.length} suggestions covered\n\n${escapeSlack(group.summary)}\n\nExample reports (${examples.length} of ${group.ticketIds.length}; complete report coverage is saved in the dashboard): ${examples.map((ticketId) => `https://app.clickup.com/t/${encodeURIComponent(ticketId)}`).join(" ")}\nSummary ${run.id.slice(0, 12)}`;
      if (text.length > 39000) {
        delivery.state = "failed";
        delivery.error =
          "Summary exceeds Slack message limit. Nothing sent for this module.";
        continue;
      }
      delivery.state = "sending";
      delete delivery.error;
      await saveRun(run);
      try {
        let channel = delivery.destination;
        if (channel.startsWith("U")) {
          const dm = await slack(
            "conversations.open",
            { users: channel },
            fetcher,
          );
          if (dm.ok !== true || !dm.channel?.id) {
            delivery.state = "failed";
            delivery.error = `Slack could not open PM conversation: ${String(
              dm.error || "unknown_error",
            )
              .replace(/[^a-z_]/g, "")
              .slice(0, 60)}`;
            await saveRun(run);
            continue;
          }
          channel = dm.channel.id;
        }
        const result = await slack(
          "chat.postMessage",
          { channel, text, unfurl_links: false, unfurl_media: false },
          fetcher,
        );
        if (result.ok === true && typeof result.ts === "string") {
          delivery.state = "sent";
          delivery.timestamp = result.ts;
        } else if (result.ok === false) {
          delivery.state = "failed";
          delivery.error = `Slack declined the message: ${String(
            result.error || "unknown_error",
          )
            .replace(/[^a-z_]/g, "")
            .slice(0, 60)}`;
        } else {
          delivery.state = "unknown";
          delivery.error =
            "Slack returned an incomplete delivery receipt. Check Slack manually; automatic retry is blocked.";
        }
      } catch {
        delivery.state = "unknown";
        delivery.error =
          "Slack delivery could not be confirmed. Check Slack manually; automatic retry is blocked to avoid duplicates.";
      }
      await saveRun(run);
    }
    await saveRun(run);
    return run;
  });
}
