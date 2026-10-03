import { sendRun } from "@/lib/slack";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireLocalRequest(request);
    const { id } = await context.params;
    return Response.json(await sendRun(id));
  } catch (e) {
    return failure(e);
  }
}
