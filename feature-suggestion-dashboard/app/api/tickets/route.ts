import { fetchSuggestions } from "@/lib/clickup";
import { failure, requireLocalRequest } from "@/lib/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    requireLocalRequest(request);
    return Response.json(
      await fetchSuggestions(
        fetch,
        new URL(request.url).searchParams.get("refresh") === "true",
      ),
    );
  } catch (error) {
    return failure(error);
  }
}
