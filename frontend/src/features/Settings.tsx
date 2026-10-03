import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LockKeyhole, CheckCircle2, AlertCircle, History } from "lucide-react";
import {
  loadSettings,
  previewPriority,
  type QueuePreview,
  patch,
  post,
  parseObject,
  type SettingsData,
  type Registry,
  type RegistryField,
} from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "../components/ui/dialog";
import {
  Field,
  FieldLabel,
  FieldDescription,
  FieldGroup,
} from "../components/ui/field";
import { Loading, Failure, Technical, SelectField } from "../components/shared";
import KnowledgeEditor from "./settings/KnowledgeEditor";
import OwnershipEditor from "./settings/OwnershipEditor";
import { cn } from "../lib/utils";
const sections = [
  ["agents", "Agents"],
  ["sources", "Data sources"],
  ["channels", "Channels"],
  ["knowledge", "Knowledge"],
  ["ownership", "Team and ownership"],
  ["priority", "Priority rules"],
  ["safety", "Safety"],
] as const;
export default function Settings() {
  const [params, setParams] = useSearchParams();
  const section = params.get("section") || "agents";
  const q = useQuery({
    queryKey: ["settings"],
    queryFn: loadSettings,
  });
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [baseline, setBaseline] = useState<SettingsData | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [test, setTest] = useState<unknown>(null);
  const [sample, setSample] = useState("");
  const [agentTest, setAgentTest] = useState<string | null>(null);
  const [priorityPreview, setPriorityPreview] = useState<QueuePreview | null>(
    null,
  );
  const client = useQueryClient();
  useEffect(() => {
    if (q.data && !config) {
      setConfig(structuredClone(q.data.config));
      setBaseline(structuredClone(q.data));
    }
  }, [q.data]);
  const dirty =
    config !== null &&
    baseline !== null &&
    JSON.stringify(config) !== JSON.stringify(baseline.config);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: MouseEvent) => {
      const a = (e.target as HTMLElement)?.closest("a");
      if (a && !window.confirm("Leave Settings with unsaved changes?")) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, [dirty]);
  function choose(s: string) {
    if (
      dirty &&
      !window.confirm(
        "Unsaved changes remain. Keep editing these settings in the next section?",
      )
    )
      return;
    setParams((p) => {
      p.set("section", s);
      return p;
    });
  }
  const update = (group: string, id: string, key: string, value: unknown) =>
    setConfig((c) => {
      const v = structuredClone(c || {});
      if (!group) {
        v[key] = value;
        return v;
      }
      const g = parseObject(v[group]);
      if (id) {
        g[id] = { ...parseObject(g[id]), [key]: value };
        v[group] = g;
      } else {
        g[key] = value;
        v[group] = g;
      }
      return v;
    });
  const save = async () => {
    setBusy(true);
    try {
      const result = await patch<SettingsData>("/ui/settings", {
        version: baseline?.version,
        reviewer,
        config,
      });
      client.setQueryData(["settings"], result);
      setConfig(structuredClone(result.config));
      setBaseline(structuredClone(result));
      setConfirm(false);
      toast.success("Settings saved. Changes are recorded in Activity.");
      await client.invalidateQueries({ queryKey: ["overview"] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  async function runTest(path: string, body: unknown = {}) {
    setBusy(true);
    try {
      const result = await post(path, body);
      setTest(result);
      if (path.endsWith("/restore")) {
        setConfig(null);
        setBaseline(null);
        await client.invalidateQueries({ queryKey: ["settings"] });
      }
      await client.invalidateQueries({ queryKey: ["overview"] });
    } catch (e) {
      setTest({ error: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
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
  if (!config) return <Loading />;
  const registries = q.data.registries;
  const sources = registries.connectors || [];
  return (
    <main className="settings-page">
      <header className="page-heading">
        <div>
          <h1>Settings</h1>
          <p>Configuration changes are versioned and reviewed locally</p>
        </div>
        <span className="muted">
          Version {baseline?.version ?? q.data.version}
          {dirty ? " — unsaved changes" : ""}
          {baseline && baseline.version !== q.data.version
            ? " — a newer version exists; saving requires a fresh review"
            : ""}
        </span>
      </header>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {sections.map(([id, label]) => (
            <button
              key={id}
              className={cn(id === section && "active")}
              onClick={() => choose(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="settings-content">
          {section === "agents" ? (
            <>
              <h2>Agents</h2>
              <p className="muted">
                Configure each role. Locked safety checks cannot be disabled.
              </p>
              <section className="settings-group">
                <h3>Shared review thresholds</h3>
                <p className="muted">
                  These supported settings apply to future investigations.
                  Mandatory safety rules still run first.
                </p>
                <FieldGroup>
                  {Object.entries(parseObject(config.thresholds)).map(
                    ([key, value]) => (
                      <Field key={key}>
                        <FieldLabel htmlFor={`threshold-${key}`}>
                          {(
                            {
                              triage: "Sorting confidence",
                              auto: "Automatic reply confidence",
                              cluster_similarity:
                                "Similarity needed to group reports",
                              min_delivery_samples:
                                "Minimum delivery sample size",
                              min_gameplay_baseline:
                                "Minimum gameplay baseline size",
                            } as Record<string, string>
                          )[key] || key.replaceAll("_", " ")}
                        </FieldLabel>
                        <Input
                          id={`threshold-${key}`}
                          type="number"
                          min={0}
                          max={key.startsWith("min_") ? undefined : 1}
                          step={key.startsWith("min_") ? 1 : 0.01}
                          value={typeof value === "number" ? value : 0}
                          onChange={(e) =>
                            update(
                              "thresholds",
                              "",
                              key,
                              Number(e.target.value),
                            )
                          }
                        />
                      </Field>
                    ),
                  )}
                </FieldGroup>
              </section>
              {registries.agents.map((a) => (
                <section className="settings-group" key={a.id}>
                  <div className="section-heading">
                    <h3>{a.name}</h3>
                    <Badge variant="secondary">
                      {a.status || "Configured"}
                    </Badge>
                  </div>
                  <p className="muted">{a.reason}</p>
                  <RegistryForm
                    registry={a}
                    values={parseObject(parseObject(config.agents)[a.id])}
                    onChange={(key, value) =>
                      update("agents", a.id, key, value)
                    }
                  />
                  <div className="inline-actions">
                    <Button
                      variant="outline"
                      disabled={busy || a.available === false}
                      onClick={() => setAgentTest(a.id)}
                    >
                      Test on a sample ticket
                    </Button>
                    <Technical title="Instructions and version history">
                      <div className="diff-view">
                        <strong>Saved instructions</strong>
                        <pre>
                          {String(
                            parseObject(parseObject(q.data.config.agents)[a.id])
                              .instructions || "No custom instructions",
                          )}
                        </pre>
                        <strong>Unsaved instructions</strong>
                        <pre>
                          {String(
                            parseObject(parseObject(config.agents)[a.id])
                              .instructions || "No custom instructions",
                          )}
                        </pre>
                      </div>
                      {q.data.history
                        .filter((h) => Number(h.version) < q.data.version)
                        .map((h, i) => (
                          <div className="version-row" key={i}>
                            <span>
                              Version {String(h.version || i + 1)} —{" "}
                              {String(h.reviewer || "Local reviewer")}
                            </span>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={busy || a.available === false}
                              onClick={() =>
                                void runTest(`/ui/agents/${a.id}/restore`, {
                                  version: q.data.version,
                                  target_version: h.version,
                                  reviewer: reviewer || "Local reviewer",
                                })
                              }
                            >
                              Restore previous version
                            </Button>
                          </div>
                        ))}
                    </Technical>
                  </div>
                </section>
              ))}
            </>
          ) : section === "sources" ? (
            <>
              <h2>Data sources</h2>
              <p className="muted">
                Credentials stay in environment variables. Only non-secret
                settings are editable here.
              </p>
              {sources.map((s) => (
                <section className="settings-group" key={s.id}>
                  <div className="section-heading">
                    <h3>{s.name}</h3>
                    <span className="source-status">
                      {s.status === "connected" ? (
                        <CheckCircle2 />
                      ) : (
                        <AlertCircle />
                      )}
                      {s.status?.replaceAll("_", " ") || "Not configured"}
                    </span>
                  </div>
                  <p className="muted">{s.reason}</p>
                  <small className="muted">
                    Last successful check:{" "}
                    {s.last_check
                      ? new Date(s.last_check).toLocaleString()
                      : "Not checked"}
                  </small>
                  <RegistryForm
                    registry={s}
                    values={parseObject(parseObject(config.connectors)[s.id])}
                    onChange={(key, value) =>
                      update("connectors", s.id, key, value)
                    }
                  />
                  <div className="secret-list">
                    {Object.entries({}).map(([key, status]) => (
                      <p key={key}>
                        <LockKeyhole />
                        {key}:{" "}
                        {status === "set"
                          ? "Set in environment"
                          : "Missing in environment"}
                      </p>
                    ))}
                  </div>
                  <Button
                    variant="outline"
                    disabled={busy || s.available === false}
                    onClick={() =>
                      void runTest(`/ui/connectors/${s.id}/test`, {
                        reviewer: reviewer || "Local reviewer",
                      })
                    }
                  >
                    Test connection
                  </Button>
                </section>
              ))}
            </>
          ) : section === "channels" ? (
            <>
              <h2>Channels</h2>
              <p className="muted">
                Enable an available adapter to add its reports to the shared
                queue.
              </p>
              {registries.channels.map((c) => (
                <section className="settings-group" key={c.id}>
                  <div className="section-heading">
                    <h3>{c.name}</h3>
                    <Badge variant="secondary">
                      {c.status?.replaceAll("_", " ") || "Not configured"}
                    </Badge>
                  </div>
                  <p className="muted">{c.reason}</p>
                  <RegistryForm
                    registry={c}
                    values={parseObject(parseObject(config.channels)[c.id])}
                    onChange={(key, value) =>
                      update("channels", c.id, key, value)
                    }
                  />
                  <Button
                    variant="outline"
                    disabled={busy || c.available === false}
                    onClick={() =>
                      void runTest(`/ui/channels/${c.id}/sync`, {
                        reviewer: reviewer || "Local reviewer",
                      })
                    }
                  >
                    Sync reports
                  </Button>
                </section>
              ))}
              <p>
                New adapters appear here automatically through the connector
                registry.
              </p>
            </>
          ) : section === "knowledge" ? (
            <KnowledgeEditor reviewer={reviewer} setReviewer={setReviewer} />
          ) : section === "ownership" ? (
            <OwnershipEditor
              people={Array.isArray(config.people) ? config.people : []}
              onChange={(value) => update("", "", "people", value)}
            />
          ) : section === "priority" ? (
            <>
              <h2>Priority rules</h2>
              <p className="muted">
                Adjust the weights, then preview how waiting reports move.
              </p>
              <FieldGroup>
                {Object.entries(parseObject(config.priority)).map(
                  ([key, value]) => (
                    <Field key={key}>
                      <FieldLabel htmlFor={`weight-${key}`}>
                        {(
                          {
                            paying: "Paying user bonus",
                            power_user: "100+ streak bonus",
                            streak_scale: "Points per streak day",
                            age_hour: "Points per waiting hour",
                            max_age: "Maximum counted waiting hours",
                            purchase: "Payment report bonus",
                            urgency: "Urgent report bonus",
                            negative_sentiment: "Negative feedback bonus",
                            cluster_member: "Shared problem bonus",
                            safety: "Safety report weight (minimum 1000)",
                          } as Record<string, string>
                        )[key] || key.replaceAll("_", " ")}
                      </FieldLabel>
                      <Input
                        id={`weight-${key}`}
                        type="number"
                        min={key === "safety" ? 1000 : 0}
                        step={0.01}
                        value={typeof value === "number" ? value : 0}
                        onChange={(e) =>
                          update("priority", "", key, Number(e.target.value))
                        }
                      />
                    </Field>
                  ),
                )}
              </FieldGroup>
              <Button
                variant="outline"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    setPriorityPreview(
                      await previewPriority(
                        Object.fromEntries(
                          Object.entries(parseObject(config.priority)).map(
                            ([key, value]) => [key, Number(value)],
                          ),
                        ),
                      ),
                    );
                  } catch (e) {
                    toast.error((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Preview queue changes
              </Button>
              {priorityPreview ? (
                <div className="table-scroll">
                  <p className="muted">
                    Preview only. No queue scores have been saved. First 20
                    reports by proposed priority. Proposed scores recalculate
                    waiting time and grouping from current records.
                  </p>
                  <table>
                    <thead>
                      <tr>
                        <th>Report</th>
                        <th>Current score</th>
                        <th>Proposed score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {priorityPreview.tickets.slice(0, 20).map((t) => (
                        <tr key={t.id}>
                          <td>{t.subject || "Support report"}</td>
                          <td>{t.before.toFixed(1)}</td>
                          <td>{t.after.toFixed(1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </>
          ) : (
            <>
              <h2>Safety</h2>
              <div className="safety-lock">
                <LockKeyhole />
                <h3>Safe mode: on (locked)</h3>
                <p>Data access: read-only</p>
                <p>
                  Model calls:{" "}
                  {q.data.safety.llm_enabled
                    ? "Enabled, subject to review"
                    : "Disabled"}
                </p>
                <p>{q.data.safety.real_data_model_policy}</p>
                <p>
                  Nothing is sent to users or changed in real systems. The
                  backend enforces this independently of the dashboard.
                </p>
              </div>
              <h3>Always needs a person</h3>
              <ul>
                <li>Streak restores and restore offers</li>
                <li>Payments and refund decisions</li>
                <li>Messaging restrictions and safety decisions</li>
                <li>Cheating flags and vendor escalations</li>
                <li>Internal messages and draft fixes</li>
              </ul>
              <Technical title="Safety enforcement">
                <pre>{JSON.stringify(q.data.safety, null, 2)}</pre>
              </Technical>
              <div className="secret-list">
                <h3>Credential status</h3>
                {Object.entries(q.data.secret_status).map(([key, value]) => (
                  <p key={key}>
                    <LockKeyhole />
                    {key}:{" "}
                    {value === "set"
                      ? "Set in environment"
                      : "Missing in environment"}
                  </p>
                ))}
              </div>
            </>
          )}
          {section !== "safety" && section !== "knowledge" ? (
            <footer className="settings-save">
              <Field>
                <FieldLabel htmlFor="settings-reviewer">Your name</FieldLabel>
                <Input
                  id="settings-reviewer"
                  placeholder="Recorded in Activity"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                />
              </Field>
              <Button
                disabled={!dirty || !reviewer.trim() || busy}
                onClick={() => setConfirm(true)}
              >
                Save changes
              </Button>
              {dirty ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setConfig(structuredClone(q.data.config));
                    setBaseline(structuredClone(q.data));
                  }}
                >
                  Discard changes
                </Button>
              ) : null}
            </footer>
          ) : null}
        </div>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogTitle>Review configuration changes</DialogTitle>
          <DialogDescription>
            Lowering confidence thresholds or changing agent instructions can
            reduce safeguards. Safe mode and read-only access remain locked.
            Changes apply only after you save.
          </DialogDescription>
          <Technical title="Configuration diff">
            <pre>
              {JSON.stringify(
                { saved: q.data.config, proposed: config },
                null,
                2,
              )}
            </pre>
          </Technical>
          <Button disabled={busy} onClick={() => void save()}>
            Save changes
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog open={test !== null} onOpenChange={(v) => !v && setTest(null)}>
        <DialogContent>
          <DialogTitle>Check result</DialogTitle>
          <DialogDescription>
            Connection checks and tests use read-only access. No external action
            is performed.
          </DialogDescription>
          {typeof parseObject(test).inserted === "number" ? (
            <>
              <p>
                Fetched {String(parseObject(test).fetched)} reports. Added{" "}
                {String(parseObject(test).inserted)} new reports to the local
                queue.
              </p>
              <p className="muted">
                Read-only source access. No messages or moderation actions were
                performed.
              </p>
            </>
          ) : typeof parseObject(test).error === "string" ? (
            <p>{String(parseObject(test).error)}</p>
          ) : (
            <p>Check completed. Review the recorded result below.</p>
          )}
          <Technical title="Recorded check details">
            <pre>{JSON.stringify(test, null, 2)}</pre>
          </Technical>
          <Button variant="outline" onClick={() => setTest(null)}>
            Close result
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog
        open={agentTest !== null}
        onOpenChange={(v) => !v && setAgentTest(null)}
      >
        <DialogContent>
          <DialogTitle>Test an agent on a sample</DialogTitle>
          <DialogDescription>
            Select an existing ticket ID. This preview does not save
            configuration or approve an action.
          </DialogDescription>
          <Input
            aria-label="Sample ticket ID"
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            placeholder="Ticket ID from the inbox"
          />
          <Button
            disabled={!sample.trim() || busy}
            onClick={async () => {
              await runTest(`/ui/agents/${agentTest}/test`, {
                ticket_id: sample,
                config,
                reviewer: reviewer || "Local reviewer",
              });
              setAgentTest(null);
            }}
          >
            Run sample test
          </Button>
        </DialogContent>
      </Dialog>
    </main>
  );
}
function RegistryForm({
  registry,
  values,
  onChange,
}: {
  registry: Registry;
  values: Record<string, unknown>;
  onChange: (k: string, v: unknown) => void;
}) {
  return (
    <FieldGroup>
      {registry.fields.map((f) => (
        <SchemaField
          prefix={registry.id}
          key={f.key}
          field={{ ...f, readonly: f.readonly || registry.available === false }}
          value={values[f.key]}
          onChange={(v) => onChange(f.key, v)}
        />
      ))}
    </FieldGroup>
  );
}
function SchemaField({
  prefix,
  field: f,
  value,
  onChange,
}: {
  prefix: string;
  field: RegistryField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={`setting-${prefix}-${f.key}`}>{f.label}</FieldLabel>
      {f.type === "boolean" ? (
        <label className="check-label">
          <input
            disabled={f.readonly}
            id={`setting-${prefix}-${f.key}`}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          {Boolean(value) ? "On" : "Off"}
        </label>
      ) : f.options ? (
        <select
          disabled={f.readonly}
          id={`setting-${prefix}-${f.key}`}
          value={String(value || "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {f.options.map((v) => (
            <option value={v} key={v}>
              {v}
            </option>
          ))}
        </select>
      ) : f.type === "textarea" || f.key === "instructions" ? (
        <Textarea
          disabled={f.readonly}
          id={`setting-${prefix}-${f.key}`}
          rows={5}
          value={String(value || "")}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : f.key === "confidence_threshold" ? (
        <div className="threshold-control">
          <input
            disabled={f.readonly}
            id={`setting-${prefix}-${f.key}`}
            type="range"
            min={f.minimum ?? 0.5}
            max={f.maximum ?? 1}
            step={0.01}
            value={typeof value === "number" ? value : 0.8}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <span>
            {typeof value === "number" ? Math.round(value * 100) : 80}%
            confidence required
          </span>
          <small>
            Lower: more review needed. Higher: stronger evidence required.
          </small>
        </div>
      ) : f.type === "number" || f.type === "integer" ? (
        <Input
          disabled={f.readonly}
          id={`setting-${prefix}-${f.key}`}
          type="number"
          min={f.minimum ?? undefined}
          max={f.maximum ?? undefined}
          step={f.type === "integer" ? 1 : 0.01}
          value={typeof value === "number" ? value : 0}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      ) : f.type === "array" || f.type === "object" ? (
        <JsonField
          id={`setting-${prefix}-${f.key}`}
          value={value ?? (f.type === "array" ? [] : {})}
          disabled={f.readonly}
          onChange={onChange}
        />
      ) : (
        <Input
          disabled={f.readonly}
          id={`setting-${prefix}-${f.key}`}
          value={String(value || "")}
          onChange={(e) => onChange(e.target.value)}
        />
      )}{" "}
      {f.description ? (
        <FieldDescription>{f.description}</FieldDescription>
      ) : null}
    </Field>
  );
}

function JsonField({
  id,
  value,
  disabled,
  onChange,
}: {
  id: string;
  value: unknown;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState(false);
  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    setError(false);
  }, [value]);
  return (
    <>
      <Textarea
        id={id}
        rows={3}
        disabled={disabled}
        value={text}
        aria-invalid={error}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const next = JSON.parse(e.target.value);
            setError(false);
            onChange(next);
          } catch {
            setError(true);
          }
        }}
      />
      {error ? (
        <small>Complete a valid list or object before saving this field.</small>
      ) : null}
    </>
  );
}
