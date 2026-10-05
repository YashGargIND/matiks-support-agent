export type Ticket = {
  id: string;
  title: string;
  body: string;
  createdAt: string;
  status: string;
  url: string;
};
export type Module = {
  id: string;
  name: string;
  keywords: string[];
  destination: string;
};
export type Config = { modules: Module[] };
export type Summary = {
  moduleId: string;
  summary: string;
  ticketIds: string[];
};
export type Delivery = {
  state: "unsent" | "sending" | "sent" | "failed" | "unknown" | "unconfigured";
  destination: string;
  error?: string;
  timestamp?: string;
};
export type Run = {
  scope?: "all" | "demo";
  sourceTickets?: number;
  snapshotAt?: string;
  id: string;
  createdAt: string;
  totalTickets: number;
  fetchedTasks: number;
  modelCalls: number;
  config: Config;
  summaries: Summary[];
  deliveries: Record<string, Delivery>;
};
export type Job = {
  scope?: "all" | "demo";
  sourceTickets?: number;
  snapshotAt?: string;
  id: string;
  status:
    | "queued"
    | "fetching"
    | "summarizing"
    | "sending"
    | "done"
    | "error"
    | "interrupted";
  createdAt: string;
  updatedAt: string;
  send: boolean;
  config: Config;
  fetchedPages: number;
  fetchedTasks: number;
  totalTickets: number;
  completedBatches: number;
  totalBatches: number;
  run?: Run;
  error?: string;
  owner: string;
};
