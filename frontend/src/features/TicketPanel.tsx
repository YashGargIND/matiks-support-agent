import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  X,
  Crown,
  Flame,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  MoreHorizontal,
} from "lucide-react";
import { toast } from "sonner";
import {
  loadTicket,
  updateTicket,
  investigateTicket,
  approveReply,
  approveAction,
  confidence,
  categories,
  relative,
  reportSummary,
  statusLabel,
  money,
  parseObject,
  type Ticket,
  type Action,
  type Evidence,
} from "../lib/api";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "../components/ui/dialog";
import { Field, FieldLabel } from "../components/ui/field";
import { Loading, Failure, Technical, SelectField } from "../components/shared";
const actionLabels: Record<string, string> = {
  restore_streak: "Approve restore",
  offer_paid_restore: "Approve restore offer",
  temp_ban_messaging: "Review messaging restriction",
  flag_cheating: "Approve investigation flag",
  escalate_purchase: "Approve payment review",
  vendor_ticket: "Approve vendor review",
  slack_message: "Approve internal note",
  draft_pr: "Approve draft fix",
  feature_to_pm: "Approve feature review",
};
export default function TicketPanel({
  ticket: initial,
  onClose,
  onResolved,
}: {
  ticket: Ticket;
  onClose: () => void;
  onResolved: () => void;
}) {
  const client = useQueryClient();
  const [params] = useSearchParams();
  const q = useQuery({
    queryKey: ["ticket", initial.id, initial.revision],
    queryFn: () => loadTicket(initial.id),
  });
  const t = q.data?.ticket || initial;
  const [draft, setDraft] = useState(t.reply_draft);
  const [original, setOriginal] = useState(false);
  const [excerpt, setExcerpt] = useState(false);
  const [review, setReview] = useState(false);
  const [reviewAction, setReviewAction] = useState<Action | null>(null);
  const [reviewer, setReviewer] = useState(
    params.get("person") === "everyone" ? "" : params.get("person") || "",
  );
  const [more, setMore] = useState(false);
  const [assigned, setAssigned] = useState(t.assigned_to || "");
  const [category, setCategory] = useState(t.category);
  const reply = useRef<HTMLTextAreaElement>(null);
  const safety = t.category === "dm_safety";
  useEffect(() => {
    setDraft(t.reply_draft);
    setOriginal(false);
    setExcerpt(false);
    setCategory(t.category);
    setAssigned(t.assigned_to || "");
  }, [t.id, t.revision]);
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["overview"] }),
      client.invalidateQueries({ queryKey: ["ticket"] }),
      client.invalidateQueries({ queryKey: ["activity"] }),
      client.invalidateQueries({ queryKey: ["problems"] }),
    ]);
  };
  const mutate = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),
    onSuccess: invalidate,
    onError: (e) => toast.error(e.message),
  });
  const approve = async () => {
    if (!reviewer.trim()) {
      toast.error("Add your name to record this approval.");
      return;
    }
    if (!reviewAction && draft !== t.reply_draft) {
      await mutate.mutateAsync(() =>
        updateTicket(t.id, {
          reviewer,
          revision: t.revision,
          reply_draft: draft,
        }),
      );
      toast.success("Reply saved. Review it again before approval.");
      setReview(false);
      return;
    }
    await mutate.mutateAsync(() =>
      reviewAction
        ? approveAction(reviewAction.id, { reviewer, revision: t.revision })
        : approveReply(t.id, { reviewer, revision: t.revision }),
    );
    toast.success(
      reviewAction
        ? "Action approved. Safe mode is on, so nothing was changed."
        : "Reply approved. Safe mode is on, so nothing was sent.",
    );
    setReview(false);
    setReviewAction(null);
    if (!reviewAction) onResolved();
  };
  const escalate = async () => {
    await mutate.mutateAsync(() =>
      updateTicket(t.id, {
        reviewer: reviewer || "Local reviewer",
        revision: t.revision,
        status: "escalated",
        escalation_reason: "Sent to a person from inbox review",
      }),
    );
    toast.success("Sent to a person for review.");
    onResolved();
  };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        (e.target.matches("input,textarea,select") ||
          e.target.isContentEditable)
      )
        return;
      const k = e.key.toLowerCase();
      if (k === "e") {
        reply.current?.focus();
      }
      if (k === "a" && t.reply_draft) {
        setReviewAction(null);
        setReview(true);
      }
      if (k === "p") void escalate();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [t]);
  if (q.isPending) return <Loading />;
  if (q.error) return <Failure error={q.error} retry={() => q.refetch()} />;
  const evidence = q.data?.evidence || [];
  const unavailable = evidence.filter((e) => !e.available);
  const replyPending =
    q.data?.actions?.some(
      (a) => a.type === "send_reply" && a.status === "pending",
    ) || false;
  const actions =
    q.data?.actions?.filter(
      (a) => a.status === "pending" && a.type !== "send_reply",
    ) || [];
  return (
    <div className="ticket-panel">
      <div className="panel-scroll">
        <header className="ticket-header">
          <div>
            <h2>{t.user_identifier || "User redacted"}</h2>
            <div className="inline-meta">
              <span>
                {t.channel === "clickup"
                  ? "ClickUp"
                  : t.channel === "email"
                    ? "Email"
                    : t.channel}
              </span>
              <span title={new Date(t.created_at).toLocaleString()}>
                {relative(t.created_at)}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Close ticket panel"
            onClick={onClose}
          >
            <X />
          </Button>
        </header>
        {t.provenance === "synthetic" ? (
          <p className="unavailable">
            Synthetic example · account, evidence and policy are demo fixtures.
            They do not establish a live Matiks policy.
          </p>
        ) : null}
        <p className="muted">
          {statusLabel(t)}
          {t.status === "resolved"
            ? " · recorded locally; nothing sent or changed in real systems"
            : ""}
        </p>
        <div className="cohort-labels">
          {t.cohort.is_paying === true ? (
            <span>
              <Crown />
              Paying user
            </span>
          ) : null}
          {t.cohort.streak_days !== null ? (
            <span>
              <Flame />
              {t.cohort.streak_days}-day streak
            </span>
          ) : null}
          {t.cohort.is_paying === null || t.cohort.streak_days === null ? (
            <span className="muted">
              Cohort{" "}
              {t.cohort.is_paying === null && t.cohort.streak_days === null
                ? "unknown"
                : "partly verified"}
            </span>
          ) : null}
          {safety ? (
            <Badge variant="destructive">
              <ShieldAlert />
              Safety
            </Badge>
          ) : null}
        </div>
        <details className="priority-explanation">
          <summary>
            Priority {Math.round(t.priority_score)}:{" "}
            {Object.entries(t.priority_breakdown)
              .filter(([, v]) => v > 0)
              .map(([k]) => k.replaceAll("_", " "))
              .join(", ") || "standard review"}
          </summary>
          <dl>
            {Object.entries(t.priority_breakdown).map(([k, v]) => (
              <div key={k}>
                <dt>{k.replaceAll("_", " ")}</dt>
                <dd>{v.toFixed(1)}</dd>
              </div>
            ))}
          </dl>
        </details>
        <section className="panel-section">
          {t.injection_flag ? (
            <p className="unavailable">
              Instructions in the report text were flagged for human review.
            </p>
          ) : null}
          <h3>What happened</h3>
          <p className="two-lines">
            {safety
              ? "A private messaging report needs individual safety review."
              : reportSummary(t)}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOriginal(!original)}
          >
            {original ? "Hide original message" : "See original message"}
          </Button>
          {original ? (
            <div className="original-message">
              <small>Personal details redacted</small>
              {safety && !excerpt ? (
                <Button variant="outline" onClick={() => setExcerpt(true)}>
                  Show excerpt
                </Button>
              ) : (
                <p>{t.body}</p>
              )}
            </div>
          ) : null}
        </section>
        <section className="panel-section">
          <h3>What the AI found</h3>
          <p>
            {t.verdict
              ? t.internal_summary || t.verdict.replaceAll("_", " ")
              : "This report has not been investigated yet."}
          </p>
          <span
            className="confidence"
            title={
              t.confidence === null
                ? "No confidence assessment"
                : `${Math.round(t.confidence * 100)}%`
            }
          >
            {(t.confidence ?? 0) >= 0.85 ? <CheckCircle2 /> : <AlertCircle />}
            {confidence(t.confidence)}
          </span>
          {evidence
            .filter((e) => e.available)
            .slice(0, 5)
            .map((e) => (
              <div className="evidence-note" key={e.id}>
                <span>{evidenceSummary(e)}</span>
                <a
                  href={`#evidence-${e.id}`}
                  onClick={() => {
                    document
                      .querySelector<HTMLDetailsElement>("#evidence-details")
                      ?.setAttribute("open", "");
                  }}
                >
                  {e.source}
                </a>
              </div>
            ))}
          {unavailable.length ? (
            <p className="unavailable">
              Couldn't check:{" "}
              {unavailable.map((e) => sourceLabel(e.tool)).join(", ")}. See Data
              sources in Settings.
            </p>
          ) : null}
          {t.escalation_reason ? (
            <p className="muted">Needs a person: {t.escalation_reason}</p>
          ) : null}
          {!["resolved", "closed"].includes(t.status) ? (
            <Button
              variant="outline"
              disabled={mutate.isPending}
              onClick={async () => {
                await mutate.mutateAsync(() =>
                  investigateTicket(t.id, {
                    reviewer: reviewer || "Local reviewer",
                    revision: t.revision,
                  }),
                );
                toast.success("Report investigated. Review the evidence.");
              }}
            >
              {t.active_run ? "Refresh investigation" : "Investigate report"}
            </Button>
          ) : null}
        </section>
        <section className="panel-section">
          <div className="section-heading">
            <h3>Suggested reply</h3>
            <small>
              {t.language === "hi"
                ? "Hindi"
                : t.language === "hinglish"
                  ? "Hinglish"
                  : "English"}
            </small>
          </div>
          <Field>
            <FieldLabel className="sr-only" htmlFor={`reply-${t.id}`}>
              Suggested reply
            </FieldLabel>
            <Textarea
              ref={reply}
              id={`reply-${t.id}`}
              value={draft}
              placeholder="Investigate this report before preparing a reply."
              onChange={(e) => setDraft(e.target.value)}
              rows={5}
            />
          </Field>
          {draft !== t.reply_draft ? (
            <div className="inline-actions">
              <small>Unsaved reply changes</small>
              <Button
                variant="outline"
                size="sm"
                disabled={mutate.isPending}
                onClick={async () => {
                  await mutate.mutateAsync(() =>
                    updateTicket(t.id, {
                      reviewer: reviewer || "Local reviewer",
                      revision: t.revision,
                      reply_draft: draft,
                    }),
                  );
                  toast.success("Reply saved.");
                }}
              >
                Save reply
              </Button>
            </div>
          ) : null}
          {q.data?.guard_note ? (
            <p className="muted guard-note">{q.data.guard_note}</p>
          ) : null}
          {q.data?.fact_checks?.length ? (
            <Technical title="Fact check review">
              <pre>{JSON.stringify(q.data.fact_checks, null, 2)}</pre>
            </Technical>
          ) : null}
        </section>
        {actions.length ? (
          <section className="panel-section">
            <h3>Suggested action</h3>
            {actions.map((a) => (
              <div className="suggested-action" key={a.id}>
                <strong>{a.type.replaceAll("_", " ")}</strong>
                <p>{a.reason}</p>
                {a.type === "temp_ban_messaging" ? (
                  <p>
                    Recommended restriction:{" "}
                    {String(parseObject(a.payload).days ?? "unknown")} days.
                    Severity:{" "}
                    {String(parseObject(a.payload).severity ?? "unknown")}.{" "}
                    {t.provenance === "synthetic"
                      ? "This range is a synthetic fixture, not a Matiks policy."
                      : "Usual restrictions are 7–30 days; the reviewer must confirm the duration for the evidence and severity."}
                  </p>
                ) : null}
                <Technical title="Action details">
                  <pre>{JSON.stringify(parseObject(a.payload), null, 2)}</pre>
                </Technical>
                <Button
                  variant="outline"
                  disabled={mutate.isPending}
                  onClick={() => {
                    setReviewAction(a);
                    setReview(true);
                  }}
                >
                  {actionLabels[a.type] || "Review action"}
                </Button>
              </div>
            ))}
          </section>
        ) : null}
        <details id="evidence-details" className="technical panel-section">
          <summary>Technical details</summary>
          <Technical title="What the AI checked">
            {evidence.map((e) => (
              <div id={`evidence-${e.id}`} key={e.id}>
                <strong>
                  {e.tool.replaceAll("_", " ")}:{" "}
                  {e.available ? "Available" : "Unavailable"}
                </strong>
                <small className="block">
                  {e.source}, fetched {new Date(e.fetched_at).toLocaleString()}
                </small>
                {safety && !excerpt ? (
                  <Button variant="outline" onClick={() => setExcerpt(true)}>
                    Show excerpt
                  </Button>
                ) : (
                  <pre>{JSON.stringify(e.data, null, 2)}</pre>
                )}
              </div>
            ))}
            <pre>{JSON.stringify(q.data?.tool_calls || [], null, 2)}</pre>
          </Technical>
          <Technical title="Logs">
            <p>
              {evidence.some((e) => e.tool === "read_gcp_logs" && e.available)
                ? "Available log evidence is included under What the AI checked."
                : "App logs were not available for this investigation."}
            </p>
          </Technical>
          <Technical title="Root cause">
            <p>
              {t.root_cause_hypothesis || "No verified root cause recorded."}
            </p>
          </Technical>
          <Technical title="Code and draft fix">
            <p>No reviewed patch attached to this ticket.</p>
          </Technical>
          <Technical title="Fact check">
            <pre>{JSON.stringify(q.data?.fact_checks || [], null, 2)}</pre>
          </Technical>
          <Technical title="Cost">
            <p>
              {q.data?.llm_calls?.length
                ? `Recorded cost: ${money(q.data.llm_calls.some((c) => typeof c.cost_usd !== "number") ? null : q.data.llm_calls.reduce((sum, c) => sum + (typeof c.cost_usd === "number" ? c.cost_usd : 0), 0))}`
                : "No model calls recorded for this report."}
            </p>
            <pre>{JSON.stringify(q.data?.llm_calls || [], null, 2)}</pre>
          </Technical>
        </details>
        <Technical title="History">
          {q.data?.events?.length ? (
            q.data.events.map((e, i) => (
              <div className="history-event" key={i}>
                <strong>{e.kind.replaceAll("_", " ")}</strong>
                <small>{new Date(e.created_at).toLocaleString()}</small>
                <pre>{JSON.stringify(parseObject(e.data), null, 2)}</pre>
              </div>
            ))
          ) : (
            <p>No review history recorded.</p>
          )}
        </Technical>
      </div>
      <footer className="ticket-actions">
        <Button
          disabled={
            !draft ||
            mutate.isPending ||
            t.status === "closed" ||
            (t.status === "resolved" && !replyPending)
          }
          onClick={() => {
            setReviewAction(null);
            setReview(true);
          }}
        >
          {safety ? "Review and decide" : "Approve reply"}
        </Button>
        <Button variant="secondary" onClick={() => reply.current?.focus()}>
          Edit reply
        </Button>
        <Button
          variant="ghost"
          disabled={mutate.isPending}
          onClick={() => void escalate()}
        >
          Send to a person
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="More ticket actions"
          onClick={() => setMore(true)}
        >
          <MoreHorizontal />
        </Button>
      </footer>
      <Dialog open={review} onOpenChange={setReview}>
        <DialogContent>
          <DialogTitle>
            {reviewAction
              ? "Review suggested action"
              : safety
                ? "Review and decide"
                : "Approve this reply"}
          </DialogTitle>
          <DialogDescription>
            Safe mode is on. This approval is recorded locally; nothing is sent
            or changed in real systems.
            {safety ? " Safety decisions always need individual review." : ""}
          </DialogDescription>
          {t.provenance === "synthetic" ? (
            <p className="unavailable">
              Synthetic example. All policy and account evidence here are demo
              fixtures.
            </p>
          ) : null}
          <p>{reviewAction ? reviewAction.reason : draft}</p>
          {reviewAction?.type === "temp_ban_messaging" ? (
            <p>
              Proposed duration:{" "}
              {String(parseObject(reviewAction.payload).days ?? "unknown")}{" "}
              days. Severity:{" "}
              {String(parseObject(reviewAction.payload).severity ?? "unknown")}.
              Review the recorded evidence before approving.
            </p>
          ) : null}
          <Field>
            <FieldLabel htmlFor="reviewer">
              Your name for the review history
            </FieldLabel>
            <input
              id="reviewer"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="Reviewer name"
            />
          </Field>
          <Button
            disabled={!reviewer.trim() || mutate.isPending}
            onClick={() =>
              void (safety && !draft && !reviewAction
                ? escalate().then(() => setReview(false))
                : approve())
            }
          >
            {draft !== t.reply_draft && !reviewAction
              ? "Save changes before approval"
              : reviewAction
                ? actionLabels[reviewAction.type] || "Approve action"
                : "Approve reply"}
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog open={more} onOpenChange={setMore}>
        <DialogContent>
          <DialogTitle>Update this report</DialogTitle>
          <DialogDescription>
            Changes are recorded in the local review history.
          </DialogDescription>
          <SelectField
            label="Category"
            value={category}
            onChange={(v) => setCategory(v as Ticket["category"])}
            options={Object.entries(categories).map(([value, label]) => ({
              value,
              label,
            }))}
          />
          <Field>
            <FieldLabel>Assign to</FieldLabel>
            <input
              value={assigned}
              onChange={(e) => setAssigned(e.target.value)}
              placeholder="Person from ownership settings"
            />
          </Field>
          <Button
            disabled={mutate.isPending}
            onClick={async () => {
              await mutate.mutateAsync(() =>
                updateTicket(t.id, {
                  revision: t.revision,
                  reviewer: reviewer || "Local reviewer",
                  category,
                  assigned_to: assigned || null,
                }),
              );
              setMore(false);
              toast.success("Report updated.");
            }}
          >
            Save report changes
          </Button>
          <Button
            variant="outline"
            disabled={mutate.isPending}
            onClick={async () => {
              await mutate.mutateAsync(() =>
                updateTicket(t.id, {
                  revision: t.revision,
                  reviewer: reviewer || "Local reviewer",
                  status: "closed",
                  escalation_reason: "Marked as not an issue by a person",
                }),
              );
              setMore(false);
              toast.success("Report closed.");
              onResolved();
            }}
          >
            Mark as not an issue
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const toolLabels: Record<string, string> = {
  resolve_user: "User identity",
  get_user_cohort: "Cohort records",
  get_streak_history: "Streak history",
  get_activity_logs: "Activity records",
  get_shield_history: "Shield history",
  read_gcp_logs: "App logs",
  get_order_history: "Order history",
  get_delivery_samples: "Delivery records",
  get_purchase_history: "Purchase records",
  get_merch_orders: "Merch orders",
  get_merch_delivery_stats: "Delivery sample records",
  get_chat_history: "Chat evidence",
  review_chat_report: "Chat evidence",
  compare_gameplay: "Gameplay comparison",
  investigate_code: "Codebase evidence",
  find_owners: "Ownership evidence",
};
function sourceLabel(tool: string) {
  return toolLabels[tool] || tool.replaceAll("_", " ");
}
function evidenceSummary(e: Evidence) {
  const d = e.data;
  if (e.tool === "resolve_user")
    return d.verified === true || d.identity_verified === true
      ? "User identity matched verified account records."
      : "Account records were checked; identity still needs verification.";
  if (e.tool === "get_user_cohort") {
    const parts = [];
    if (typeof d.streak_days === "number")
      parts.push(`${d.streak_days}-day streak recorded`);
    if (d.is_paying === true) parts.push("paying status verified");
    return parts.length
      ? parts.join("; ") + "."
      : "Cohort records were checked; paying or streak status remains unknown.";
  }
  if (d.incident_history_complete === false)
    return `${sourceLabel(e.tool)} checked; incident-time coverage is incomplete.`;
  return `Checked ${sourceLabel(e.tool).toLowerCase()}. Open the source for its recorded details.`;
}
