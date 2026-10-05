import { getJob, publicJob } from "@/lib/jobs";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireLocalRequest(request);
    const { id } = await context.params;
    return Response.json({ job: publicJob(await getJob(id)) });
  } catch (e) {
    return failure(e);
  }
}
