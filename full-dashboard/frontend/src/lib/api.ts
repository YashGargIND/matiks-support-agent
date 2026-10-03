import createClient from "openapi-fetch";
import type { paths, components } from "./schema";
export const api = createClient<paths>({
  baseUrl: "",
  fetch: async (input) => {
    try {
      return await fetch(input);
    } catch {
      throw new ApiError(
        0,
        "Can't reach the local support service. Start the API and try again.",
      );
    }
  },
});
api.use({
  async onResponse({ response }) {
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = (await response.clone().json()).detail;
      } catch {}
      throw new ApiError(
        response.status,
        typeof detail === "string"
          ? detail
          : `Request failed (${response.status}). Refresh and try again.`,
      );
    }
    return response;
  },
});
function data<T>(result: { data?: T; response: Response }): T {
  if (result.data === undefined)
    throw new ApiError(
      result.response.status,
      "The local service returned an empty response.",
    );
  return result.data;
}
export const loadOverview = async (
  provenance: "real" | "synthetic" | "all" = "real",
) =>
  data(
    await api.GET("/ui/overview", { params: { query: { provenance } } }),
  ) as Overview;
export const loadTicket = async (ticket_id: string) =>
  data(
    await api.GET("/ui/tickets/{ticket_id}", {
      params: { path: { ticket_id } },
    }),
  ) as TicketDetail;
export const loadSettings = async () => data(await api.GET("/ui/settings"));
export const loadKnowledge = async () => data(await api.GET("/ui/knowledge"));
export const loadInsights = async (query: {
  person: string;
  start?: string;
  end?: string;
}) => data(await api.GET("/ui/insights", { params: { query } }));
export const loadActivity = async (query: {
  person: string;
  provenance: "real" | "synthetic" | "all";
}) => data(await api.GET("/ui/activity", { params: { query } }));
export const loadProblems = async (
  person: string,
  provenance: "real" | "synthetic" = "real",
) =>
  data(
    await api.GET("/ui/problems", {
      params: { query: { person, provenance } },
    }),
  );
export const loadProblem = async (
  problem_id: string,
  person: string,
  provenance: "real" | "synthetic" = "real",
) =>
  data(
    await api.GET("/ui/problems/{problem_id}", {
      params: { path: { problem_id }, query: { person, provenance } },
    }),
  );
export const loadPipeline = async (person: string) =>
  data(await api.GET("/ui/pipeline", { params: { query: { person } } }));
export type QueuePreview = components["schemas"]["QueuePreview"];
export const previewPriority = async (priority: Record<string, number>) =>
  data(await api.POST("/ui/priority-preview", { body: { priority } }));
export const createReport = async (body: components["schemas"]["NewReport"]) =>
  data(await api.POST("/ui/reports", { body })) as Ticket;
export const createDemo = async (
  scenario: string,
  body: components["schemas"]["Reviewed"],
) =>
  data(
    await api.POST("/ui/demo/{scenario}", {
      params: { path: { scenario } },
      body,
    }),
  ) as Ticket;
export type TicketEdit = components["schemas"]["TicketEdit"];
export type Approval = components["schemas"]["support__ui_api__Approval"];
export const updateTicket = async (ticket_id: string, body: TicketEdit) =>
  data(
    await api.PATCH("/ui/tickets/{ticket_id}", {
      params: { path: { ticket_id } },
      body,
    }),
  );
export const investigateTicket = async (ticket_id: string, body: Approval) =>
  data(
    await api.POST("/ui/tickets/{ticket_id}/process", {
      params: { path: { ticket_id } },
      body,
    }),
  );
export const approveReply = async (ticket_id: string, body: Approval) =>
  data(
    await api.POST("/ui/tickets/{ticket_id}/approve", {
      params: { path: { ticket_id } },
      body,
    }),
  );
export const approveAction = async (action_id: string, body: Approval) =>
  data(
    await api.POST("/ui/actions/{action_id}/approve", {
      params: { path: { action_id } },
      body,
    }),
  );
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      0,
      "Can't reach the local support service. Start the API and try again.",
    );
  }
  let data: unknown;
  try {
    data = await r.json();
  } catch {
    throw new ApiError(
      r.status,
      "Can't reach the local support service. Start the API and try again.",
    );
  }
  if (!r.ok) {
    const d = data as { detail?: unknown };
    throw new ApiError(
      r.status,
      typeof d.detail === "string"
        ? d.detail
        : `Request failed (${r.status}). Refresh and try again.`,
    );
  }
  return data as T;
}
export const post = <T>(path: string, data: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export type Category = components["schemas"]["Category"];
export type Ticket = Required<components["schemas"]["Ticket"]> & {
  cohort: Required<components["schemas"]["Cohort"]>;
};
export type Evidence = Required<components["schemas"]["Evidence"]>;
export type Action = components["schemas"]["ActionRow"];
export type Event = components["schemas"]["EventRow"];
export type TicketDetail = Omit<
  components["schemas"]["TicketDetailResponse"],
  "ticket" | "evidence"
> & { ticket: Ticket; evidence: Evidence[] };
export type Person = components["schemas"]["Person"];
export type Overview = Omit<
  components["schemas"]["OverviewResponse"],
  "tickets"
> & { tickets: Ticket[] };
export type Problem = components["schemas"]["ProblemResponse"];
export type ProblemDetail = components["schemas"]["ProblemDetailResponse"];
export type RegistryField = components["schemas"]["RegistryField"];
export type Registry = components["schemas"]["Registry"] & {
  description?: string;
  secret_status?: Record<string, string>;
};
export type SettingsData = components["schemas"]["SettingsResponse"];
export const categories: Record<Category, string> = {
  account: "Account",
  feature: "Feature requests",
  gameplay_bug: "Gameplay bugs",
  app_bug: "App bugs",
  streak: "Streaks",
  purchase: "Payments",
  dm_safety: "Safety",
  cheating: "Cheating",
  merch: "Merch",
  other: "Other",
};
export const statusLabel = (t: Pick<Ticket, "status" | "resolution_type">) =>
  t.status === "escalated"
    ? "Needs a person"
    : t.status === "drafted"
      ? "Ready for review"
      : t.status === "resolved"
        ? t.resolution_type === "auto"
          ? "Resolved by AI"
          : "Resolved"
        : t.status === "closed"
          ? "Closed"
          : t.status === "investigating"
            ? "Investigating"
            : "Open";
export const confidence = (n: number | null) =>
  n === null
    ? "Not assessed"
    : n >= 0.85
      ? "Confident"
      : n >= 0.6
        ? "Needs review"
        : "Unsure";
export const money = (n: number | null | undefined) =>
  n == null
    ? "Not measured"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      }).format(n);
export function duration(n: number | null | undefined) {
  if (n == null) return "Not measured";
  return n < 60
    ? `${Math.round(n)}s`
    : `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
}
export function relative(s: string) {
  const h = Math.max(0, (Date.now() - Date.parse(s)) / 3600000);
  return h < 1
    ? `waiting ${Math.max(1, Math.floor(h * 60))}m`
    : h < 24
      ? `waiting ${Math.floor(h)}h`
      : `waiting ${Math.floor(h / 24)}d`;
}
export function parseObject(data: unknown): Record<string, unknown> {
  if (typeof data === "string") {
    try {
      return JSON.parse(data);
    } catch {
      return { text: data };
    }
  }
  return data && typeof data === "object"
    ? (data as Record<string, unknown>)
    : {};
}

export function reportSummary(t: Pick<Ticket, "subject" | "body">) {
  const generic =
    /^(feedback report|feature suggestion|suggestion)(?:\s*[·-]|$)|^(?:re:\s*)?matiks privacy policy update/i.test(
      t.subject,
    );
  const text = generic || !t.subject ? t.body : t.subject;
  return text.replace(/\s+/g, " ").trim().slice(0, 140) || "Support report";
}
