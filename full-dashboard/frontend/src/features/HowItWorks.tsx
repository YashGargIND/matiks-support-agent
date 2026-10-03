import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LockKeyhole,
  ArrowDown,
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
  Shield,
  Route,
  UserRound,
  Sparkles,
  Bug,
  Flame,
  CreditCard,
  ShoppingBag,
  Gamepad2,
  SearchCheck,
  Inbox,
  UserCheck,
  PackageCheck,
  type LucideIcon,
} from "lucide-react";
import { loadPipeline, categories, type Category } from "../lib/api";
import { Loading, Failure } from "../components/shared";
import { cn } from "../lib/utils";
interface Step {
  id: string;
  label: string;
  count: number | null;
  description: string;
  settings_section: string;
}
const branchDescriptions: Record<string, string> = {
  account:
    "Checks account identity and the recorded account issue. Account changes need a person.",
  feature:
    "Records the suggestion and looks for product ownership. An acknowledgement does not promise a release.",
  gameplay_bug:
    "Checks incident evidence and relevant code before proposing a cause or fix.",
  app_bug:
    "Checks app evidence and relevant code. Missing logs remain visible.",
  streak:
    "Checks dated play, streak and historical shield evidence before suggesting a restore. A restore needs human approval.",
  purchase:
    "Checks verified purchase evidence. Payment and refund decisions need a person.",
  dm_safety:
    "Critical safety reports go immediately to a person. Other messaging reports require individual evidence and human review.",
  cheating:
    "Compares available gameplay evidence before suggesting further review. Any flag needs a person.",
  merch:
    "Checks the order and matching delivered samples. Historical delivery ranges are estimates, not fixed delivery dates.",
};
const icons: Record<string, LucideIcon> = {
  channels: Database,
  clean: FileText,
  rules: Shield,
  sorting: Route,
  account: UserRound,
  feature: Sparkles,
  gameplay_bug: Bug,
  app_bug: Bug,
  streak: Flame,
  purchase: CreditCard,
  dm_safety: Shield,
  cheating: Gamepad2,
  merch: ShoppingBag,
  fact_checker: SearchCheck,
  outcomes: Inbox,
  human_approval: UserCheck,
  outbox: PackageCheck,
};
const labels: Record<string, string> = {
  channels: "Channels",
  clean: "Clean and enrich",
  rules: "Safety rules and grouping",
  sorting: "Sorting agent",
  specialists: "Specialist agents",
  fact_checker: "Fact checker",
  outcomes: "Review outcomes",
  human_approval: "Human approval",
  outbox: "Safe-mode outbox",
};
export default function HowItWorks() {
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string>("");
  const q = useQuery({
    queryKey: ["pipeline", params.get("person")],
    queryFn: () => loadPipeline(params.get("person") || "everyone"),
    refetchInterval: 10000,
  });
  const choice = [...(q.data?.steps || []), ...(q.data?.branches || [])].find(
    (s) => s.id === selected,
  );
  return (
    <main className="standard-page pipeline-page">
      <div className="page-heading">
        <div>
          <h1>How it works</h1>
          <p>One support queue. Evidence before every decision.</p>
        </div>
        <span className="live-label">
          <CheckCircle2 />
          Counts update from local activity
        </span>
      </div>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <Failure error={q.error} retry={() => q.refetch()} />
      ) : (
        <>
          <h2 className="flow-heading">From report to investigation</h2>
          <div className="pipeline-flow">
            {q.data.steps
              .filter((s) =>
                ["channels", "clean", "rules", "sorting"].includes(s.id),
              )
              .map((s, i) => (
                <StepCard
                  key={s.id}
                  step={s}
                  selected={selected === s.id}
                  onSelect={() => setSelected(s.id)}
                  arrow={i < 3}
                />
              ))}
          </div>
          <div className="pipeline-branches">
            <div className="branch-label">
              <ArrowDown />
              <h2>Nine specialist branches</h2>
              <p>Each checks the evidence for its category</p>
            </div>
            <div className="branch-list">
              {q.data.branches
                .filter((s) => s.id !== "other")
                .map((s) => {
                  const Icon = icons[s.id] || UserRound;
                  return (
                    <button
                      key={s.id}
                      className={cn(selected === s.id && "selected")}
                      onClick={() => setSelected(s.id)}
                    >
                      <Icon />
                      <span>{categories[s.id as Category] || s.label}</span>
                      <strong>{s.count ?? "—"}</strong>
                      <ArrowRight />
                    </button>
                  );
                })}
            </div>
            {q.data.branches.find((s) => s.id === "other") ? (
              <button
                className="fallback-branch"
                onClick={() => setSelected("other")}
              >
                Other reports:{" "}
                {q.data.branches.find((s) => s.id === "other")?.count ?? "—"}{" "}
                completed investigations today
              </button>
            ) : null}
          </div>
          <section className="step-explanation">
            <h2>{choice?.label || "Follow a report through the pipeline"}</h2>
            <p>
              {(choice && branchDescriptions[choice.id]) ||
                choice?.description ||
                "Select any step or specialist to see what it checks. Counts reflect local events today; they do not claim that replies were sent or actions were executed."}
            </p>
            {choice ? (
              <Link to={`/settings?section=${choice.settings_section}`}>
                Open relevant settings
              </Link>
            ) : null}
          </section>
          <h2 className="flow-heading">From review to local resolution</h2>
          <div className="pipeline-flow">
            {q.data.steps
              .filter((s) =>
                [
                  "fact_checker",
                  "outcomes",
                  "human_approval",
                  "outbox",
                ].includes(s.id),
              )
              .map((s, i) => (
                <StepCard
                  key={s.id}
                  step={s}
                  selected={selected === s.id}
                  onSelect={() => setSelected(s.id)}
                  arrow={i < 3}
                />
              ))}
          </div>
          <div className="pipeline-safety">
            <LockKeyhole />
            <p>
              <strong>Human decisions stay visible.</strong> Approvals enter a
              local outbox. No user receives a message, and no streak, payment,
              or moderation state changes.
            </p>
          </div>
        </>
      )}
    </main>
  );
}

function StepCard({
  step: s,
  selected,
  onSelect,
  arrow,
}: {
  step: Step;
  selected: boolean;
  onSelect: () => void;
  arrow: boolean;
}) {
  const Icon = icons[s.id] || FileText;
  return (
    <div className="pipeline-stage">
      <button
        className={cn("pipeline-step", selected && "selected")}
        onClick={onSelect}
      >
        <Icon />
        <span>{labels[s.id] || s.label}</span>
        <p>{s.description}</p>
        <small>
          <strong>{s.count ?? "—"}</strong>{" "}
          {s.id === "outbox" ? "local outbox entries" : "today"}
        </small>
      </button>
      {arrow ? <ArrowRight className="flow-arrow" /> : null}
    </div>
  );
}
