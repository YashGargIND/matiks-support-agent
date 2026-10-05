import type { Ticket } from "./types";
type Task = {
  id: string;
  name?: string;
  description?: string;
  text_content?: string;
  markdown_description?: string;
  date_created?: string;
  status?: { status?: string };
  custom_fields?: {
    id: string;
    value?: unknown;
    type_config?: {
      options?: { id?: string; name?: string; orderindex?: number }[];
    };
  }[];
};
export function isSuggestion(task: Task, listId = process.env.CLICKUP_LIST_ID) {
  const fieldId =
    process.env.CLICKUP_TOPIC_FIELD_ID ||
    (listId === "901611930428" ? "a5e3ce45-2379-4f5d-945b-b2dc9db92917" : "");
  const field = task.custom_fields?.find((f) => f.id === fieldId);
  const value = String(field?.value ?? "");
  const option = field?.type_config?.options?.find(
    (o) => String(o.id) === value || String(o.orderindex) === value,
  );
  return (
    /^suggestion:|^feature request:/i.test(task.name || "") ||
    /^(suggestion|feature request)$/i.test(option?.name || "") ||
    (Boolean(field) &&
      (value ===
        (process.env.CLICKUP_SUGGESTION_OPTION ||
          "2cc005ec-16a0-44cb-9a1f-a6737e867e25") ||
        (listId === "901611930428" && value === "1")))
  );
}
type PageProgress = { pages: number; fetchedTasks: number };
async function fetchAllSuggestions(
  fetcher: typeof fetch = fetch,
  onPage?: (progress: PageProgress) => Promise<void>,
) {
  const token = process.env.CLICKUP_API_TOKEN;
  const listId = process.env.CLICKUP_LIST_ID;
  if (!token || !listId || !/^\d+$/.test(listId))
    throw new Error(
      "Configure CLICKUP_API_TOKEN and numeric CLICKUP_LIST_ID in .env.local.",
    );
  const unique = new Map<string, Task>();
  let page = 0;
  let previous = "";
  while (true) {
    const url = new URL(`https://api.clickup.com/api/v2/list/${listId}/task`);
    url.search = new URLSearchParams({
      page: String(page),
      include_closed: "true",
      subtasks: "true",
      order_by: "created",
      reverse: "false",
    }).toString();
    let response: Response;
    let attempts = 0;
    while (true) {
      response = await fetcher(url, {
        headers: { Authorization: token },
        cache: "no-store",
        signal: AbortSignal.timeout(30000),
      });
      if (response.status !== 429 || attempts >= 3) break;
      const reset = Number(response.headers.get("X-RateLimit-Reset"));
      const retryAfter = Number(response.headers.get("Retry-After"));
      const wait =
        reset > 0
          ? Math.max(0, reset * 1000 - Date.now()) + 100
          : retryAfter > 0
            ? retryAfter * 1000
            : NaN;
      if (!Number.isFinite(wait) || wait > 60000) break;
      await new Promise((resolve) => setTimeout(resolve, wait));
      attempts++;
    }
    if (!response.ok)
      throw new Error(
        `ClickUp could not fetch reports (HTTP ${response.status}). Check list access or retry later.`,
      );
    const data = await response.json();
    if (!Array.isArray(data.tasks))
      throw new Error("ClickUp returned an invalid report page.");
    const tasks: Task[] = data.tasks;
    const signature = tasks.map((t) => t.id).join(",");
    if (tasks.length && signature === previous)
      throw new Error(
        "ClickUp repeated a page. No partial dataset will be summarized.",
      );
    for (const task of tasks) {
      if (typeof task.id !== "string")
        throw new Error("ClickUp returned a report without an ID.");
      unique.set(task.id, task);
    }
    await onPage?.({ pages: page + 1, fetchedTasks: unique.size });
    if (data.last_page === true || tasks.length === 0) break;
    previous = signature;
    page++;
    if (page > 1000)
      throw new Error(
        "The list exceeds 100,000 reports. No partial dataset will be summarized.",
      );
  }
  const tickets: Ticket[] = [...unique.values()]
    .filter((t) => isSuggestion(t, listId))
    .map((t) => ({
      id: t.id,
      title: t.name || "Untitled suggestion",
      body: t.description || t.text_content || t.markdown_description || "",
      createdAt: /^\d+$/.test(t.date_created || "")
        ? new Date(Number(t.date_created)).toISOString()
        : "",
      status: t.status?.status || "Unknown",
      url: `https://app.clickup.com/t/${encodeURIComponent(t.id)}`,
    }));
  return {
    tickets,
    fetchedTasks: unique.size,
    pages: page + 1,
    complete: true as const,
    fetchedAt: new Date().toISOString(),
  };
}
type Snapshot = Awaited<ReturnType<typeof fetchAllSuggestions>>;
const cache = globalThis as typeof globalThis & {
  featureClickupCache?: {
    key: string;
    snapshot?: Snapshot;
    expires: number;
    pending?: Promise<Snapshot>;
    listeners?: Set<(progress: PageProgress) => Promise<void>>;
  };
};
export async function fetchSuggestions(
  fetcher: typeof fetch = fetch,
  force = false,
  onPage?: (progress: PageProgress) => Promise<void>,
): Promise<Snapshot> {
  if (fetcher !== fetch) return fetchAllSuggestions(fetcher, onPage);
  const key = `${process.env.CLICKUP_LIST_ID}:${process.env.CLICKUP_TOPIC_FIELD_ID}:${process.env.CLICKUP_SUGGESTION_OPTION}`;
  if (!cache.featureClickupCache || cache.featureClickupCache.key !== key)
    cache.featureClickupCache = { key, expires: 0 };
  const state = cache.featureClickupCache;
  state.listeners ??= new Set();
  if (onPage) state.listeners.add(onPage);
  if (state.pending) {
    try {
      return await state.pending;
    } finally {
      if (onPage) state.listeners.delete(onPage);
    }
  }
  if (!force && state.snapshot && state.expires > Date.now()) {
    if (onPage) {
      state.listeners.delete(onPage);
      await onPage({
        pages: state.snapshot.pages,
        fetchedTasks: state.snapshot.fetchedTasks,
      });
    }
    return state.snapshot;
  }
  state.pending = fetchAllSuggestions(fetcher, async (progress) => {
    await Promise.allSettled(
      [...state.listeners!].map((listener) => listener(progress)),
    );
  })
    .then((snapshot) => {
      state.snapshot = snapshot;
      state.expires = Date.now() + 300000;
      return snapshot;
    })
    .finally(() => {
      state.pending = undefined;
    });
  try {
    return await state.pending;
  } finally {
    if (onPage) state.listeners.delete(onPage);
  }
}
