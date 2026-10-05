import type { Summary } from "../lib/types";
// Provider fixtures use short refs; the server alone creates real-ID coverage.
export function assignmentFixture(groups: Summary[], modules = ["other"]) {
  return {
    assignments: Object.fromEntries(
      groups.flatMap((group) =>
        group.ticketIds.map((ref) => [ref, group.moduleId]),
      ),
    ),
    summaries: Object.fromEntries(
      modules.map((module) => [
        module,
        groups.find((group) => group.moduleId === module)?.summary || "",
      ]),
    ),
  };
}
export function fixtureResponse(
  value: unknown,
  modules = ["other"],
  status = 200,
) {
  const body = value as { choices?: { message: { content: string } }[] };
  if (body.choices?.[0]?.message?.content) {
    const result = JSON.parse(body.choices[0].message.content);
    if (result.groups)
      body.choices[0].message.content = JSON.stringify(
        assignmentFixture(result.groups, modules),
      );
  }
  return Response.json(body, { status });
}
