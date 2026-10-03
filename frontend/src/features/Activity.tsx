import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, LockKeyhole } from "lucide-react";
import { Button } from "../components/ui/button";
import { Field, FieldLabel } from "../components/ui/field";
import { Loading, Failure, NoItems, SelectField } from "../components/shared";
import { loadActivity, parseObject, type Event } from "../lib/api";
interface ActivityEvent extends Event {
  time: string;
  actor: string;
  summary: string;
  safe_mode: boolean;
  problem_id?: string;
}
export default function Activity() {
  const [params, setParams] = useSearchParams();
  const [actor, setActor] = useState("");
  const [type, setType] = useState("");
  const [date, setDate] = useState("");
  const [page, setPage] = useState(0);
  const q = useQuery({
    queryKey: [
      "activity",
      params.get("person"),
      params.get("provenance") || "real",
    ],
    queryFn: () =>
      loadActivity({
        person: params.get("person") || "everyone",
        provenance:
          params.get("provenance") === "synthetic" ? "synthetic" : "real",
      }).then((events) =>
        events.map((e) => {
          const data = parseObject(e.data);
          return {
            ...e,
            time: e.created_at || "",
            actor: String(data.reviewer || data.agent || "Support agent"),
            summary:
              (
                {
                  ingest: "Added report to the queue",
                  run_finished: "Finished an investigation",
                  internal_approval: "Approved suggested action",
                  reply_approval: "Approved reply",
                  demo_example_created: "Created a synthetic example",
                  report_created: "Created a local report",
                  ingested: "Added report to the queue",
                  processed: "Investigated a report",
                  fact_check: "Checked reply claims",
                  approved: "Approved reply",
                  action_approved: "Approved suggested action",
                  settings_updated: "Saved configuration changes",
                  facts_updated: "Saved knowledge entries",
                  channel_sync_review: "Checked read-only channel import",
                  live_source_mapping_review: "Reviewed live source mapping",
                  source_capture: "Captured read-only source evidence",
                  source_setup_failed: "Could not check a data source",
                  identity_resolved: "Verified a user identity",
                  clustered: "Grouped similar reports",
                } as Record<string, string>
              )[e.kind] || e.kind.replaceAll("_", " "),
            safe_mode: [
              "internal_approval",
              "reply_approval",
              "approved",
              "reply_approved",
              "action_approved",
              "auto_resolved",
              "outbox_created",
              "channel_sync_review",
            ].includes(e.kind),
          };
        }),
      ),
    refetchInterval: 15000,
  });
  const list = (q.data || []).filter(
    (e) =>
      (!actor || e.actor === actor) &&
      (!type || e.kind === type) &&
      (!date || e.time.startsWith(date)),
  );
  const exportCsv = () => {
    const escape = (v: unknown) =>
      '"' +
      (typeof v === "string" && /^[=+\-@\t\r]/.test(v)
        ? "'" + v
        : String(v ?? "")
      ).replaceAll('"', '""') +
      '"';
    const csv = [
      "Time,Who,What,Ticket,Safe mode",
      ...list.map((e) =>
        [
          e.time,
          e.actor,
          e.summary,
          e.ticket_id,
          e.safe_mode ? "Not sent" : "Local event",
        ]
          .map(escape)
          .join(","),
      ),
    ].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "matiks-support-activity.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <main className="standard-page">
      <div className="page-heading">
        <div>
          <h1>Activity</h1>
          <p>A record of decisions, checks, and local approvals</p>
        </div>
        <Button variant="outline" disabled={!list.length} onClick={exportCsv}>
          <Download data-icon="inline-start" />
          Export CSV
        </Button>
      </div>
      <div className="activity-filters">
        <SelectField
          label="Report provenance"
          value={params.get("provenance") || "real"}
          onChange={(v) => {
            setParams((p) => {
              p.set("provenance", v);
              return p;
            });
            setPage(0);
          }}
          options={[
            { value: "real", label: "Real support reports" },
            { value: "synthetic", label: "Synthetic demo examples" },
          ]}
        />

        <SelectField
          label="Person or agent"
          value={actor}
          onChange={(v) => {
            setActor(v);
            setPage(0);
          }}
          options={[
            { value: "", label: "Everyone" },
            ...[...new Set((q.data || []).map((e) => e.actor))].map((s) => ({
              value: s,
              label: s,
            })),
          ]}
        />
        <SelectField
          label="Action type"
          value={type}
          onChange={(v) => {
            setType(v);
            setPage(0);
          }}
          options={[
            { value: "", label: "All actions" },
            ...[...new Set((q.data || []).map((e) => e.kind))].map((s) => ({
              value: s,
              label: s.replaceAll("_", " "),
            })),
          ]}
        />
        <Field>
          <FieldLabel htmlFor="activity-date">Date</FieldLabel>
          <input
            id="activity-date"
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              setPage(0);
            }}
          />
        </Field>
      </div>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <Failure error={q.error} retry={() => q.refetch()} />
      ) : list.length === 0 ? (
        <NoItems
          title="No activity matches these filters"
          description="Try another date or action type."
        />
      ) : (
        <div className="activity-list">
          {list.slice(page * 40, (page + 1) * 40).map((e, i) => (
            <article key={e.id || i}>
              <time dateTime={e.time} title={new Date(e.time).toLocaleString()}>
                {new Date(e.time).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                <small>{new Date(e.time).toLocaleDateString()}</small>
              </time>
              <div>
                <strong>{e.summary || e.kind.replaceAll("_", " ")}</strong>
                <p>
                  {e.actor || "Support agent"}
                  {e.ticket_id ? (
                    <Link
                      to={`/?ticket=${e.ticket_id}&provenance=${params.get("provenance") || "real"}`}
                    >
                      Review report
                    </Link>
                  ) : null}
                </p>
                <details>
                  <summary>Details</summary>
                  <pre>{JSON.stringify(parseObject(e.data), null, 2)}</pre>
                </details>
              </div>
              {e.safe_mode ? (
                <span className="safe-marker">
                  <LockKeyhole />
                  Safe mode: not sent
                </span>
              ) : null}
            </article>
          ))}
        </div>
      )}
      <div className="pagination">
        <span>{list.length} events</span>
        <Button
          variant="ghost"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </Button>
        <Button
          variant="ghost"
          disabled={(page + 1) * 40 >= list.length}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </main>
  );
}
