import { getConfig, saveConfig } from "@/lib/storage";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    requireLocalRequest(request);
    return Response.json({
      config: await getConfig(),
      credentials: {
        clickup: Boolean(
          process.env.CLICKUP_API_TOKEN && process.env.CLICKUP_LIST_ID,
        ),
        openrouter: Boolean(process.env.OPENROUTER_API_KEY),
        slack: Boolean(process.env.SLACK_BOT_TOKEN),
      },
    });
  } catch (e) {
    return failure(e);
  }
}
export async function PUT(request: Request) {
  try {
    requireLocalRequest(request);
    await saveConfig(await request.json());
    return Response.json({ config: await getConfig() });
  } catch (e) {
    return failure(e);
  }
}
