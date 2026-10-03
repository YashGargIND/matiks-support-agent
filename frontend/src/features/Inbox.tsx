import { useMemo, useState, useEffect, type RefObject } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { type UseQueryResult, useQueryClient } from "@tanstack/react-query";
import {
  Crown,
  Flame,
  Mail,
  ListChecks,
  X,
  Plus,
  ChevronLeft,
  ChevronRight,
  Layers,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Loading, Failure, NoItems, SelectField } from "../components/shared";
import {
  categories,
  statusLabel,
  relative,
  reportSummary,
  money,
  duration,
  post,
  type Ticket,
  type Overview,
} from "../lib/api";
import NewReport from "./NewReport";
import TicketPanel from "./TicketPanel";
import { cn } from "../lib/utils";
const PAGE_SIZE = 25;
export default function Inbox({
  overview,
  onHelp,
  searchRef,
}: {
  overview: UseQueryResult<Overview, Error>;
  onHelp: () => void;
  searchRef: RefObject<HTMLInputElement | null>;
}) {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(0);
  const [density, setDensity] = useState("comfortable");
  const [saveView, setSaveView] = useState(false);
  const [newReport, setNewReport] = useState(false);
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const selected = params.get("ticket");
  const person = params.get("person") || "everyone";
  const filters = ["status", "category", "channel", "cohort", "sort"];
  const update = (key: string, value: string) => {
    if (key !== "ticket") setPage(0);
    setParams((p) => {
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });
  };
  const owner = overview.data?.people?.find((p) => p.id === person);
  const all = (overview.data?.tickets || []).filter(
    (t) =>
      t.provenance === (params.get("provenance") || "real") &&
      (person === "everyone" ||
        t.assigned_to === person ||
        owner?.categories?.includes(t.category)),
  );
  const list = useMemo(
    () =>
      all
        .filter((t) => {
          const s = params.get("status") || "attention";
          const c = params.get("category");
          const channel = params.get("channel");
          const cohort = params.get("cohort");
          const search = (params.get("search") || "").toLowerCase();
          return (
            (s === "all" || s === "attention"
              ? !["resolved", "closed"].includes(t.status) || s === "all"
              : s === t.status) &&
            (!c ||
              (c === "bugs"
                ? ["app_bug", "gameplay_bug"].includes(t.category)
                : c === t.category)) &&
            (!channel || channel === t.channel) &&
            (!cohort ||
              (cohort === "paying"
                ? t.cohort.is_paying === true
                : cohort === "power"
                  ? (t.cohort.streak_days ?? 0) >= 100
                  : cohort === "vip"
                    ? t.cohort.is_paying === true ||
                      (t.cohort.streak_days ?? 0) >= 100
                    : cohort === "unknown"
                      ? t.cohort.is_paying === null ||
                        t.cohort.streak_days === null
                      : true)) &&
            (!search ||
              `${t.subject} ${t.body} ${t.user_identifier} ${t.id}`
                .toLowerCase()
                .includes(search))
          );
        })
        .sort((a, b) =>
          params.get("sort") === "newest"
            ? Date.parse(b.created_at) - Date.parse(a.created_at)
            : params.get("sort") === "waiting"
              ? Date.parse(a.created_at) - Date.parse(b.created_at)
              : b.priority_score - a.priority_score,
        ),
    [all, params],
  );
  const entries: { id: string; members: Ticket[]; cluster: boolean }[] = [];
  for (const t of list) {
    const members = t.cluster_id
      ? list.filter((member) => member.cluster_id === t.cluster_id)
      : [t];
    const cluster = members.length > 1;
    const id = cluster ? t.cluster_id! : t.id;
    if (!entries.some((e) => e.id === id))
      entries.push({ id, members, cluster });
  }
  const filterKey = [
    person,
    ...filters.map((k) => params.get(k)),
    params.get("search"),
    params.get("provenance"),
  ].join("|");
  useEffect(() => setPage(0), [filterKey]);
  const focus =
    list.find((t) => t.id === selected) || all.find((t) => t.id === selected);
  const next = () => {
    const i = list.findIndex((t) => t.id === selected);
    const target = list[Math.min(i + 1, list.length - 1)];
    update("ticket", target?.id || "");
    if (target)
      setPage(
        Math.floor(
          entries.findIndex((e) => e.members.some((t) => t.id === target.id)) /
            PAGE_SIZE,
        ),
      );
  };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        (e.target.matches("input,textarea,select") ||
          e.target.isContentEditable)
      )
        return;
      if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === "?") onHelp();
      if (e.key === "Escape") update("ticket", "");
      if (e.key.toLowerCase() === "j") next();
      if (e.key.toLowerCase() === "k") {
        const i = list.findIndex((t) => t.id === selected);
        const target = list[Math.max(0, i - 1)];
        update("ticket", target?.id || "");
        if (target)
          setPage(
            Math.floor(
              entries.findIndex((e) =>
                e.members.some((t) => t.id === target.id),
              ) / PAGE_SIZE,
            ),
          );
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [list, selected]);
  const today = new Date().toISOString().slice(0, 10);
  const resolved = all.filter((t) => t.resolved_at?.startsWith(today));
  const stats = overview.data?.stats || {};
  const channels = [...new Set(all.map((t) => t.channel))];
  return (
    <main className={cn("inbox-page", focus && "panel-open")}>
      <section className="queue-column">
        <div className="page-heading">
          <div>
            <h1>Inbox</h1>
            <p>Work that needs your attention</p>
          </div>
          <div className="inline-actions">
            <Button size="sm" onClick={() => setNewReport(true)}>
              <Plus data-icon="inline-start" />
              New report
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSaveView(true)}>
              <Plus data-icon="inline-start" />
              Save view
            </Button>
          </div>
        </div>
        {params.get("provenance") === "synthetic" ? (
          <div className="demo-notice">
            <span>Demo examples. Excluded from real support metrics.</span>
            <Button
              size="xs"
              variant="outline"
              onClick={() =>
                setParams((p) => {
                  p.delete("provenance");
                  p.delete("ticket");
                  return p;
                })
              }
            >
              Return to real reports
            </Button>
          </div>
        ) : null}
        <div className="stats-strip">
          {[
            {
              label: "Open",
              value: all.filter(
                (t) => !["resolved", "closed"].includes(t.status),
              ).length,
              key: "status",
              filter: "attention",
            },
            {
              label: "VIPs waiting",
              value: all.filter(
                (t) =>
                  !["resolved", "closed"].includes(t.status) &&
                  (t.cohort.is_paying === true ||
                    (t.cohort.streak_days ?? 0) >= 100),
              ).length,
              key: "cohort",
              filter: "vip",
            },
            {
              label: "Resolved today",
              value: resolved.length,
              key: "status",
              filter: "resolved",
            },
            {
              label: "Avg time to resolve",
              value: duration(stats.avg_resolution_seconds),
              key: "status",
              filter: "resolved",
            },
            {
              label: "Cost per resolved",
              value: money(stats.cost_per_resolved),
              key: "status",
              filter: "resolved",
            },
          ].map((s) => (
            <button key={s.label} onClick={() => update(s.key, s.filter)}>
              <strong
                title={
                  s.label === "Avg time to resolve"
                    ? "From local ingest to resolution; active review time is measured separately."
                    : undefined
                }
              >
                {overview.data ? s.value : "—"}
              </strong>
              <span>{s.label}</span>
            </button>
          ))}
        </div>
        <div className="filters">
          <SelectField
            label="Status"
            value={params.get("status") || "attention"}
            onChange={(v) => update("status", v)}
            options={[
              { value: "attention", label: "Needs attention" },
              { value: "all", label: "All statuses" },
              { value: "open", label: "Open" },
              { value: "drafted", label: "Ready for review" },
              { value: "escalated", label: "Needs a person" },
              { value: "resolved", label: "Resolved" },
            ]}
          />
          <SelectField
            label="Category"
            value={params.get("category") || ""}
            onChange={(v) => update("category", v)}
            options={[
              { value: "", label: "All categories" },
              ...Object.entries(categories).map(([value, label]) => ({
                value,
                label,
              })),
              { value: "bugs", label: "All bugs" },
            ]}
          />
          <SelectField
            label="Channel"
            value={params.get("channel") || ""}
            onChange={(v) => update("channel", v)}
            options={[
              { value: "", label: "All channels" },
              ...channels.map((c) => ({
                value: c,
                label:
                  c === "email"
                    ? "Email"
                    : c === "clickup"
                      ? "ClickUp"
                      : c === "in_app"
                        ? "In-app DM"
                        : c === "demo"
                          ? "Demo"
                          : c,
              })),
            ]}
          />
          <SelectField
            label="Cohort"
            value={params.get("cohort") || ""}
            onChange={(v) => update("cohort", v)}
            options={[
              { value: "", label: "Everyone" },
              { value: "paying", label: "Paying" },
              { value: "power", label: "100+ streak" },
              { value: "vip", label: "VIP only" },
              { value: "unknown", label: "Unknown" },
            ]}
          />
          <SelectField
            label="Sort"
            value={params.get("sort") || "priority"}
            onChange={(v) => update("sort", v)}
            options={[
              { value: "priority", label: "Priority" },
              { value: "newest", label: "Newest" },
              { value: "waiting", label: "Waiting longest" },
            ]}
          />
        </div>
        {overview.data?.sources?.some(
          (s) => s.status === "failing" || s.status === "unverified",
        ) ? (
          <div className="source-notice">
            <span>
              Some evidence is unavailable. Reports remain in the queue.
            </span>
            <Link to="/settings?section=sources">Check data sources</Link>
          </div>
        ) : null}
        <div className="queue-controls">
          <span>
            {overview.data
              ? `${list.length} ${list.length === 1 ? "report" : "reports"}`
              : overview.error
                ? "Reports unavailable"
                : "Loading reports"}
          </span>
          <div className="inline-actions">
            <ToggleGroup
              type="single"
              value={density}
              onValueChange={(v) => v && setDensity(v)}
              aria-label="Queue density"
            >
              <ToggleGroupItem
                value="comfortable"
                aria-label="Comfortable density"
              >
                Comfortable
              </ToggleGroupItem>
              <ToggleGroupItem value="compact" aria-label="Compact density">
                Compact
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>
        {filters.some((k) => params.has(k)) ? (
          <div className="filter-chips">
            {filters
              .filter((k) => params.has(k))
              .map((k) => (
                <Button
                  variant="secondary"
                  size="xs"
                  key={k}
                  onClick={() => update(k, "")}
                >
                  {k}: {params.get(k)}
                  <X data-icon="inline-end" />
                </Button>
              ))}
            <Button
              variant="ghost"
              size="xs"
              onClick={() =>
                setParams((p) => {
                  filters.forEach((k) => p.delete(k));
                  return p;
                })
              }
            >
              Clear filters
            </Button>
          </div>
        ) : null}
        <div
          className={cn("queue-list", density === "compact" && "compact")}
          aria-label="Ticket queue"
        >
          {overview.isPending ? (
            <Loading />
          ) : overview.error ? (
            <Failure error={overview.error} retry={() => overview.refetch()} />
          ) : list.length === 0 ? (
            <NoItems description="Try another saved view, or clear filters to see the whole queue.">
              <Button
                variant="outline"
                onClick={() => setParams(new URLSearchParams({ person }))}
              >
                Clear filters
              </Button>
              <Link to="/problems">Open problems</Link>
            </NoItems>
          ) : (
            entries
              .slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
              .map((entry) =>
                entry.cluster ? (
                  <details
                    className="queue-group"
                    key={entry.id}
                    open={
                      entry.members.some((t) => t.id === selected) || undefined
                    }
                  >
                    <summary>
                      <Layers />
                      <div>
                        <strong>
                          {entry.members[0].category === "dm_safety"
                            ? "Related safety reports — review individually"
                            : reportSummary(entry.members[0])}
                        </strong>
                        <span>
                          {entry.members.length} matching reports ·{" "}
                          {new Set(
                            entry.members
                              .filter((t) => t.matiks_user_id)
                              .map((t) => t.matiks_user_id),
                          ).size || "Unknown"}{" "}
                          verified users
                        </span>
                      </div>
                    </summary>
                    <div className="group-context">
                      <Link
                        to={`/problems/${entry.id}?person=${person}&provenance=${params.get("provenance") || "real"}`}
                      >
                        Open shared problem
                      </Link>
                      <small>
                        Each report keeps its own evidence and review.
                      </small>
                    </div>
                    {entry.members.map((t) => (
                      <QueueRow
                        key={t.id}
                        ticket={t}
                        selected={selected === t.id}
                        onSelect={() => update("ticket", t.id)}
                      />
                    ))}
                  </details>
                ) : (
                  <QueueRow
                    key={entry.id}
                    ticket={entry.members[0]}
                    selected={selected === entry.members[0].id}
                    onSelect={() => update("ticket", entry.members[0].id)}
                  />
                ),
              )
          )}{" "}
        </div>
        <div className="pagination">
          <span>
            {entries.length
              ? `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, entries.length)} of ${entries.length} queue entries`
              : overview.data
                ? "0 reports"
                : "Reports unavailable"}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={page === 0}
            aria-label="Previous page"
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={(page + 1) * PAGE_SIZE >= entries.length}
            aria-label="Next page"
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </section>
      <section className="ticket-column">
        {focus ? (
          <TicketPanel
            ticket={focus}
            onClose={() => update("ticket", "")}
            onResolved={next}
          />
        ) : (
          <div className="focus-empty">
            <ListChecks />
            <h2>Select a report to review</h2>
            <p>
              See what happened, what the AI checked, and the next safe action.
            </p>
            <small>Use J and K to move through the queue.</small>
          </div>
        )}
      </section>
      <NewReport
        open={newReport}
        onOpenChange={setNewReport}
        onCreated={(id, provenance) =>
          setParams((p) => {
            p.set("ticket", id);
            if (provenance === "synthetic") p.set("provenance", "synthetic");
            else p.delete("provenance");
            return p;
          })
        }
      />
      <Dialog open={saveView} onOpenChange={setSaveView}>
        <DialogContent>
          <DialogTitle>Save this view</DialogTitle>
          <DialogDescription>
            Everyone can use these filters from the sidebar.
          </DialogDescription>
          <Input
            aria-label="Saved view name"
            placeholder="View name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button
            disabled={!name.trim()}
            onClick={async () => {
              try {
                await post("/ui/saved-views", {
                  name,
                  filters: Object.fromEntries(params),
                  reviewer: person === "everyone" ? "Local reviewer" : person,
                });
                await queryClient.invalidateQueries({ queryKey: ["overview"] });
                setSaveView(false);
                toast.success("View saved.");
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Save view
          </Button>
        </DialogContent>
      </Dialog>
    </main>
  );
}
function QueueRow({
  ticket: t,
  selected,
  onSelect,
}: {
  ticket: Ticket;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={cn("queue-row", selected && "selected")}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <div className="cohort-icons">
        {t.cohort.is_paying === true ? (
          <Crown aria-label="Paying user" />
        ) : null}
        {(t.cohort.streak_days ?? 0) >= 100 ? (
          <span>
            <Flame aria-label="100+ day streak" />
            {t.cohort.streak_days}
          </span>
        ) : null}
      </div>
      <div className="row-main">
        <strong>
          {t.category === "dm_safety"
            ? "Safety report requires individual review"
            : reportSummary(t)}
        </strong>
        <div className="row-meta">
          <span>{t.user_identifier || "User redacted"}</span>
          <span>
            {t.channel === "email" ? <Mail /> : <ListChecks />}
            {t.channel === "clickup"
              ? "ClickUp"
              : t.channel === "email"
                ? "Email"
                : t.channel === "in_app"
                  ? "In-app DM"
                  : t.channel === "demo"
                    ? "Demo"
                    : t.channel}
          </span>
        </div>
      </div>
      <div className="row-right">
        <span>{categories[t.category]}</span>
        <small title={new Date(t.created_at).toLocaleString()}>
          {relative(t.created_at)}
        </small>
        <Badge
          variant={t.category === "dm_safety" ? "destructive" : "secondary"}
        >
          {statusLabel(t)}
        </Badge>
      </div>
    </button>
  );
}
