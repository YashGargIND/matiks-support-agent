import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import {
  loadInsights,
  categories,
  money,
  duration,
  parseObject,
  type Ticket,
} from "../lib/api";
import { Loading, Failure, NoItems, SelectField } from "../components/shared";
import { Field, FieldLabel } from "../components/ui/field";
interface InsightsData {
  tickets: Ticket[];
  metrics: Record<string, unknown>;
  daily: Record<string, unknown>[];
  cost_by_model: Record<string, unknown>[];
  escalation_reasons: Record<string, unknown>[];
}
const n = (o: Record<string, unknown>, k: string) =>
  typeof o[k] === "number" ? (o[k] as number) : null;
export default function Insights() {
  const [params] = useSearchParams();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [cohort, setCohort] = useState("all");
  const q = useQuery({
    queryKey: ["insights", params.get("person"), from, to],
    queryFn: () =>
      loadInsights({
        person: params.get("person") || "everyone",
        ...(from ? { start: from } : {}),
        ...(to ? { end: to } : {}),
      }) as Promise<InsightsData>,
  });
  const tickets = q.data?.tickets || [];
  const daily = [...new Set(tickets.map((t) => t.created_at.slice(0, 10)))]
    .sort()
    .map((date) => {
      const day = tickets.filter((t) => t.created_at.startsWith(date));
      const resolved = day.filter((t) => t.resolved_at);
      const times = resolved.map((t) =>
        Math.max(
          0,
          (Date.parse(t.resolved_at!) - Date.parse(t.ingested_at)) / 1000,
        ),
      );
      return {
        date,
        open: day.filter(
          (t) => !["resolved", "closed", "escalated"].includes(t.status),
        ).length,
        resolved: day.filter((t) => ["resolved", "closed"].includes(t.status))
          .length,
        needs_person: day.filter((t) => t.status === "escalated").length,
        avg_resolution_seconds: times.length
          ? times.reduce((a, b) => a + b, 0) / times.length
          : null,
        manual_baseline_seconds: null,
      };
    });
  const topTickets = tickets.filter(
    (t) =>
      cohort === "all" ||
      (cohort === "paying"
        ? t.cohort.is_paying === true
        : (t.cohort.streak_days ?? 0) >= 100),
  );
  const counts = new Map<string, number>();
  topTickets.forEach((t) =>
    counts.set(
      categories[t.category],
      (counts.get(categories[t.category]) || 0) + 1,
    ),
  );
  const issues = [...counts]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 7);
  const handled = [
    {
      name: "Resolved automatically",
      count: tickets.filter((t) => t.resolution_type === "auto").length,
    },
    {
      name: "Reply review recorded",
      count: tickets.filter((t) => t.resolution_type === "assisted").length,
    },
    {
      name: "Needed a person",
      count: tickets.filter((t) => t.status === "escalated").length,
    },
  ];
  const bands = [
    {
      name: "Confident",
      count: tickets.filter((t) => (t.confidence ?? -1) >= 0.85).length,
    },
    {
      name: "Needs review",
      count: tickets.filter(
        (t) =>
          t.confidence !== null && t.confidence >= 0.6 && t.confidence < 0.85,
      ).length,
    },
    {
      name: "Unsure",
      count: tickets.filter((t) => t.confidence !== null && t.confidence < 0.6)
        .length,
    },
    {
      name: "Not assessed",
      count: tickets.filter((t) => t.confidence === null).length,
    },
  ];
  return (
    <main className="standard-page">
      <div className="page-heading">
        <div>
          <h1>Insights</h1>
          <p>What the support queue tells us, with gaps kept visible</p>
        </div>
        <div className="date-range">
          <Field>
            <FieldLabel htmlFor="insights-from">From</FieldLabel>
            <input
              id="insights-from"
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="insights-to">To</FieldLabel>
            <input
              id="insights-to"
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </Field>
        </div>
      </div>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <Failure error={q.error} retry={() => q.refetch()} />
      ) : tickets.length === 0 ? (
        <NoItems
          title="No reports in this date range"
          description="Change the dates to explore another period."
        />
      ) : (
        <div className="insights-grid">
          <section className="insight-section">
            <h2>{tickets.length} reports arrived in this period</h2>
            <p>Created date, grouped by current status</p>
            <Chart>
              <BarChart data={daily}>
                <Grid />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v) => String(v).slice(5)}
                />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar
                  dataKey="open"
                  stackId="a"
                  fill="var(--chart-3)"
                  name="Open"
                />
                <Bar
                  dataKey="resolved"
                  stackId="a"
                  fill="var(--chart-1)"
                  name="Resolved"
                />
                <Bar
                  dataKey="needs_person"
                  stackId="a"
                  fill="var(--chart-4)"
                  name="Needs a person"
                />
              </BarChart>
            </Chart>
          </section>
          <section className="insight-section">
            <div className="section-heading">
              <h2>
                {issues[0]
                  ? `${issues[0].name} is the most reported issue`
                  : "No verified reports in this cohort"}
              </h2>
              <SelectField
                label="Top issues cohort"
                value={cohort}
                onChange={setCohort}
                options={[
                  { value: "all", label: "Everyone" },
                  { value: "paying", label: "Paying users" },
                  { value: "power", label: "100+ streak users" },
                ]}
              />
            </div>
            <p>
              Category counts; unknown cohorts remain outside verified filters
            </p>
            {issues.length ? (
              <Chart>
                <BarChart data={issues} layout="vertical">
                  <Grid />
                  <XAxis type="number" allowDecimals={false} />
                  <YAxis dataKey="name" type="category" width={110} />
                  <Tooltip />
                  <Bar dataKey="count" name="Reports" fill="var(--chart-1)" />
                </BarChart>
              </Chart>
            ) : (
              <NoItems
                title="No verified reports for this cohort"
                description="Identity and cohort evidence are needed before comparing this group."
              />
            )}
          </section>
          <section className="insight-section">
            <h2>Resolution time needs a measured baseline</h2>
            <p>
              Time from local ingest to resolution; this is separate from
              hands-on review time
            </p>
            <Chart>
              <LineChart data={daily}>
                <Grid />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v) => String(v).slice(5)}
                />
                <YAxis tickFormatter={(v) => duration(Number(v))} />
                <Tooltip formatter={(v) => duration(Number(v))} />
                <Legend />
                <Line
                  dataKey="avg_resolution_seconds"
                  name="Recorded resolution time"
                  stroke="var(--chart-1)"
                  connectNulls={false}
                />
                <Line
                  dataKey="manual_baseline_seconds"
                  name="Manual baseline"
                  stroke="var(--chart-2)"
                  connectNulls={false}
                />
              </LineChart>
            </Chart>
            <small>
              Manual baseline:{" "}
              {duration(
                n(parseObject(q.data.metrics.handling_seconds), "manual"),
              )}
              . Time savings are unknown until matched handling samples exist.
            </small>
          </section>
          <section className="insight-section">
            <h2>{handled[2].count} reports still need a person</h2>
            <p>Current handling outcome</p>
            <Chart>
              <BarChart data={handled} layout="vertical">
                <Grid />
                <XAxis type="number" allowDecimals={false} />
                <YAxis dataKey="name" type="category" width={135} />
                <Tooltip />
                <Bar dataKey="count" name="Reports" fill="var(--chart-1)" />
              </BarChart>
            </Chart>
          </section>
          <section className="insight-section">
            <h2>
              Recorded model spend is {money(n(q.data.metrics, "spend_usd"))}
            </h2>
            <p>
              {n(q.data.metrics, "zero_llm_percent")?.toFixed(1) ?? "Unknown"}%
              of reports have no recorded model call
            </p>
            <p className="unavailable">
              Daily cost per resolution is not yet measured. Overall cost per
              resolved report: {money(n(q.data.metrics, "cost_per_resolved"))}.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Agent / model</th>
                  <th>Calls</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {q.data.cost_by_model.map((c, i) => (
                  <tr key={i}>
                    <td>
                      {String(c.agent || "Unspecified")}
                      <small>{String(c.model || "Unspecified")}</small>
                    </td>
                    <td>{String(c.calls ?? "Not measured")}</td>
                    <td>
                      {money(
                        Number(c.unknown_calls || 0) > 0
                          ? null
                          : n(c, "cost_usd"),
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <small>
              {n(q.data.metrics, "unknown_cost_calls") || 0} calls have unknown
              costs.
            </small>
          </section>
          <section className="insight-section">
            <h2>Uncertainty remains visible</h2>
            <p>Confidence assessments for current reports</p>
            <Chart>
              <BarChart data={bands}>
                <Grid />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="Reports" fill="var(--chart-2)" />
              </BarChart>
            </Chart>
            <div className="honesty-counts">
              <span>
                {n(q.data.metrics, "guard_catches") ?? "Unknown"} unsupported
                claim checks caught
              </span>
              <span>
                {n(q.data.metrics, "unavailable_tool_calls") ?? "Unknown"}{" "}
                unavailable evidence checks
              </span>
            </div>
            <details>
              <summary>Why reports needed a person</summary>
              {q.data.escalation_reasons.map((r, i) => (
                <p key={i}>
                  {String(r.reason || r.name || "Unknown")}:{" "}
                  {String(r.count ?? 0)}
                </p>
              ))}
            </details>
          </section>
        </div>
      )}
    </main>
  );
}
function Grid() {
  return <CartesianGrid stroke="var(--border)" vertical={false} />;
}
function Chart({ children }: { children: React.ReactElement }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}
