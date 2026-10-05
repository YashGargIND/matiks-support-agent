import { latestCompleteSnapshot } from "./storage";
import type { Ticket } from "./types";
export function newestDemoTickets(tickets: Ticket[]) {
  return [...tickets]
    .sort((a, b) => {
      const left = Date.parse(a.createdAt) || 0;
      const right = Date.parse(b.createdAt) || 0;
      return right - left || b.id.localeCompare(a.id);
    })
    .slice(0, 20);
}
export async function demoSnapshot() {
  const snapshot = await latestCompleteSnapshot();
  return {
    ...snapshot,
    tickets: newestDemoTickets(snapshot.tickets),
    sourceTickets: snapshot.tickets.length,
    scope: "demo" as const,
  };
}
