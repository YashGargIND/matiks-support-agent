import { useState } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Users } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "../components/ui/dialog";
import { Field, FieldLabel } from "../components/ui/field";
import {
  Loading,
  Failure,
  NoItems,
  Technical,
  SelectField,
} from "../components/shared";
import {
  loadProblems,
  loadProblem,
  post,
  categories,
  confidence,
  type Ticket,
  type Evidence,
  type Action,
} from "../lib/api";
export interface ProblemData {
  id: string;
  title: string;
  category: Ticket["category"];
  ticket_ids: string[];
  ticket_count: number;
  users_affected: number | null;
  paying_users: number;
  power_users: number;
  unknown_users: number;
  status: string;
  owner: string | null;
  summary: string;
  root_cause_hypothesis: string | null;
  confidence: number | null;
  shared_reply: string | null;
  language: string | null;
  trend_percent: number | null;
  tickets?: Ticket[];
  evidence?: Evidence[];
  actions?: Action[];
}
export default function Problems() {
  const { id } = useParams();
  return id ? <ProblemDetail id={id} /> : <ProblemList />;
}
function ProblemList() {
  const [sort, setSort] = useState("users");
  const [params] = useSearchParams();
  const q = useQuery({
    queryKey: ["problems", params.get("person"), params.get("provenance")],
    queryFn: () =>
      loadProblems(
        params.get("person") || "everyone",
        params.get("provenance") === "synthetic" ? "synthetic" : "real",
      ) as Promise<ProblemData[]>,
    refetchInterval: 15000,
  });
  return (
    <main className="standard-page">
      <div className="page-heading">
        <div>
          <h1>Problems</h1>
          <p>Shared issues that need one careful investigation</p>
        </div>
        <SelectField
          label="Rank by"
          value={sort}
          onChange={setSort}
          options={[
            { value: "users", label: "Reports affected" },
            { value: "paying", label: "Paying users affected" },
          ]}
        />
      </div>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <Failure error={q.error} retry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <NoItems
          title="No shared problems yet"
          description="Reports with matching issues appear here after investigation."
        >
          <Link to="/">Review the inbox</Link>
        </NoItems>
      ) : (
        <div className="table-scroll">
          <table className="problems-table">
            <thead>
              <tr>
                <th>Problem</th>
                <th>Reports</th>
                <th>Verified users</th>
                <th>Paying</th>
                <th>100+ streak</th>
                <th>Status</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              {[...q.data]
                .sort((a, b) =>
                  sort === "paying"
                    ? b.paying_users - a.paying_users
                    : b.ticket_count - a.ticket_count,
                )
                .map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link
                        to={`/problems/${p.id}?person=${params.get("person") || "everyone"}&provenance=${params.get("provenance") || "real"}`}
                      >
                        <strong>{p.title}</strong>
                        <small>
                          {categories[p.category]}
                          {p.trend_percent !== null
                            ? ` — ${p.trend_percent > 0 ? "up" : "down"} ${Math.abs(p.trend_percent)}% today`
                            : ""}
                        </small>
                      </Link>
                    </td>
                    <td>{p.ticket_count}</td>
                    <td>
                      {p.users_affected ?? "Unknown"}
                      {p.unknown_users ? (
                        <small>{p.unknown_users} identities unknown</small>
                      ) : null}
                    </td>
                    <td>{p.paying_users}</td>
                    <td>{p.power_users}</td>
                    <td>{p.status.replaceAll("_", " ")}</td>
                    <td>{p.owner || "Owner unresolved"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
function ProblemDetail({ id }: { id: string }) {
  const [params] = useSearchParams();
  const q = useQuery({
    queryKey: ["problem", id, params.get("person"), params.get("provenance")],
    queryFn: () =>
      loadProblem(
        id,
        params.get("person") || "everyone",
        params.get("provenance") === "synthetic" ? "synthetic" : "real",
      ) as Promise<{
        problem: ProblemData;
        tickets: Ticket[];
        evidence: Evidence[];
        actions: Action[];
      }>,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [approve, setApprove] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [pending, setPending] = useState(false);
  const client = useQueryClient();
  if (q.isPending)
    return (
      <main className="standard-page">
        <Loading />
      </main>
    );
  if (q.error)
    return (
      <main className="standard-page">
        <Failure error={q.error} retry={() => q.refetch()} />
      </main>
    );
  const p = {
    ...q.data.problem,
    tickets: q.data.tickets,
    evidence: q.data.evidence,
    actions: q.data.actions,
  };
  const reply = draft ?? p.shared_reply ?? "";
  const count =
    p.tickets?.filter(
      (t) =>
        !["resolved", "closed"].includes(t.status) &&
        t.language === p.language &&
        t.category === p.category &&
        t.category !== "dm_safety",
    ).length || 0;
  return (
    <main className="standard-page problem-detail">
      <Button variant="ghost" asChild>
        <Link to="/problems">
          <ArrowLeft data-icon="inline-start" />
          Back to problems
        </Link>
      </Button>
      <header className="page-heading">
        <div>
          <h1>{p.title}</h1>
          <p>{p.summary}</p>
        </div>
      </header>
      <div className="affected-strip">
        <span>
          <Users />
          {p.ticket_count} reports
        </span>
        <span>{p.users_affected ?? "Unknown"} verified users</span>
        <span>{p.paying_users} paying</span>
        <span>{p.power_users} with 100+ streak</span>
        <span>{p.unknown_users} identities unknown</span>
      </div>
      <section className="open-section">
        <h2>Root cause hypothesis</h2>
        <p>
          {p.root_cause_hypothesis ||
            "No verified root cause recorded. Similar wording suggests a shared issue, but does not prove the same cause."}
        </p>
        <small>
          {confidence(p.confidence)}; owner {p.owner || "unresolved"}
        </small>
        <Technical title="Technical details">
          <pre>
            {JSON.stringify(
              { evidence: p.evidence || [], actions: p.actions || [] },
              null,
              2,
            )}
          </pre>
        </Technical>
      </section>
      <section className="open-section">
        <h2>Shared reply</h2>
        <p>
          Review compatible reports together. Individual safety decisions and
          internal actions remain separate.
        </p>
        <Field>
          <FieldLabel htmlFor="shared-reply">
            Reply for affected users
          </FieldLabel>
          <Textarea
            disabled={!p.shared_reply}
            id="shared-reply"
            rows={5}
            value={reply}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="A verified shared reply is not available yet."
          />
        </Field>
        <Technical title="Preview for one user">
          <p>{reply || "Write a reply above."}</p>
          <small>{p.language || "Language not determined"}</small>
        </Technical>
        <Button
          disabled={!p.shared_reply || !reply || !count || pending}
          onClick={() => setApprove(true)}
        >
          Approve for all {count}
        </Button>
        {!p.shared_reply ? (
          <p className="muted">
            Bulk approval is unavailable until the per-ticket safety checks are
            connected. Review each affected report individually.
          </p>
        ) : null}
        {count === 0 ? (
          <small>
            No compatible unresolved reports are available for bulk approval.
          </small>
        ) : null}
      </section>
      <section className="open-section">
        <h2>Suggested internal actions</h2>
        <p>
          No verified owner or reviewed draft fix is attached. Investigate the
          cause before proposing an internal action.
        </p>
        <Link to="/settings?section=ownership">Review team and ownership</Link>
      </section>
      <Technical title={`Affected reports (${p.ticket_count})`}>
        <div className="affected-list">
          {p.tickets?.map((t) => (
            <Link
              key={t.id}
              to={`/?ticket=${t.id}&provenance=${params.get("provenance") || "real"}`}
            >
              <strong>{t.subject || t.body.slice(0, 80)}</strong>
              <small>{categories[t.category]}</small>
            </Link>
          ))}
        </div>
      </Technical>
      <Dialog open={approve} onOpenChange={setApprove}>
        <DialogContent>
          <DialogTitle>Approve {count} compatible replies</DialogTitle>
          <DialogDescription>
            Each ticket revision is checked. Safe mode is on, so nothing will be
            sent. Internal actions need separate review.
          </DialogDescription>
          <Field>
            <FieldLabel>Your name</FieldLabel>
            <Input
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </Field>
          <Button
            disabled={!reviewer.trim() || pending}
            onClick={async () => {
              setPending(true);
              try {
                await post(`/ui/problems/${id}/approve`, {
                  reviewer,
                  reply_draft: reply,
                  revisions: Object.fromEntries(
                    (p.tickets || [])
                      .filter(
                        (t) =>
                          !["resolved", "closed"].includes(t.status) &&
                          t.language === p.language &&
                          t.category === p.category &&
                          t.category !== "dm_safety",
                      )
                      .map((t) => [t.id, t.revision]),
                  ),
                });
                toast.success(
                  "Replies approved. Safe mode is on, so nothing was sent.",
                );
                setApprove(false);
                await Promise.all([
                  client.invalidateQueries({ queryKey: ["overview"] }),
                  q.refetch(),
                ]);
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setPending(false);
              }
            }}
          >
            Approve replies
          </Button>
        </DialogContent>
      </Dialog>
    </main>
  );
}
