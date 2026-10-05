"use client";
import { useEffect, useMemo, useState } from "react";
import type { Config, Ticket, Run, Job } from "@/lib/types";
import { jobActive, jobProgress } from "@/lib/job-view";
function Icon({ type }: { type: "refresh" | "search" | "send" }) {
  return (
    <svg
      width="21"
      height="21"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      {type === "search" ? (
        <>
          <circle cx="10.5" cy="10.5" r="7.5" />
          <path d="m16 16 5 5" />
        </>
      ) : type === "refresh" ? (
        <>
          <path d="M20 7v5h-5M20 12a8 8 0 1 1-2.5-6" />
        </>
      ) : (
        <>
          <path d="m3 10 18-7-7 18-3-8-8-3Z" />
          <path d="m11 13 10-10" />
        </>
      )}
    </svg>
  );
}
async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}
function moduleFor(ticket: Ticket, config: Config) {
  const text = `${ticket.title} ${ticket.body}`.toLowerCase();
  return (
    config.modules.find((m) =>
      m.keywords.some((k) => text.includes(k.toLowerCase())),
    ) ||
    config.modules.find((m) => m.id === "other") ||
    config.modules[config.modules.length - 1]
  );
}
export default function Dashboard() {
  const [demo, setDemo] = useState(false);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [config, setConfig] = useState<Config>({ modules: [] });
  const [savedConfig, setSavedConfig] = useState("");
  const [credentials, setCredentials] = useState({
    clickup: false,
    openrouter: false,
    slack: false,
  });
  const [keywordInputs, setKeywordInputs] = useState<Record<string, string>>(
    {},
  );
  const [query, setQuery] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [fetched, setFetched] = useState<{
    sourceTickets?: number;
    snapshotAt?: string;
    fetchedTasks: number;
    fetchedAt: string;
    pages: number;
  } | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const working = !!busy || jobActive(job);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const dirty = JSON.stringify(config) !== savedConfig;
  async function load(force = false, demoMode = demo) {
    setBusy(
      demoMode ? "Loading cached demo sample…" : "Fetching all ClickUp pages…",
    );
    setError("");
    try {
      const data = await api<{
        job?: Job | null;
        sourceTickets?: number;
        snapshotAt?: string;
        tickets: Ticket[];
        fetchedTasks: number;
        fetchedAt: string;
        pages: number;
      }>(
        demoMode ? "/api/demo" : `/api/tickets${force ? "?refresh=true" : ""}`,
      );
      setTickets(data.tickets);
      setFetched(data);
      if (demoMode) {
        setJob(data.job || null);
        if (data.job?.run) setRun(data.job.run);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    let active = true;
    const demoMode =
      new URLSearchParams(window.location.search).get("demo") === "1";
    setDemo(demoMode);
    api<{ config: Config; credentials: typeof credentials }>("/api/config")
      .then((data) => {
        if (active) {
          setConfig(data.config);
          setSavedConfig(JSON.stringify(data.config));
          setCredentials(data.credentials);
        }
      })
      .catch((e) => setError(e.message));
    if (!demoMode)
      api<{ job: Job | null }>("/api/summaries")
        .then(({ job }) => {
          if (active) {
            setJob(job);
            if (job?.run) setRun(job.run);
          }
        })
        .catch((e) => setError(e.message));
    void load(false, demoMode);
    return () => {
      active = false;
    };
  }, []);
  const filtered = useMemo(
    () =>
      tickets.filter(
        (t) =>
          (!query ||
            `${t.title} ${t.body}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (!moduleFilter || moduleFor(t, config)?.id === moduleFilter),
      ),
    [tickets, query, moduleFilter, config],
  );
  async function save() {
    setBusy("Saving routing…");
    setError("");
    try {
      const result = await api<{ config: Config }>(
        "/api/config",
        "PUT",
        config,
      );
      setConfig(result.config);
      setSavedConfig(JSON.stringify(result.config));
      setNotice("Module routing saved. New summaries use these destinations.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    if (!job || !jobActive(job)) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<{ job: Job }>(`/api/jobs/${job.id}`);
        if (!alive) return;
        setJob(result.job);
        if (result.job.run) setRun(result.job.run);
        setError("");
        if (!jobActive(result.job)) return;
      } catch {
        if (!alive) return;
        setError(
          "Connection lost. Reconnecting to the saved summary job; no new job or send is started.",
        );
      }
      if (alive) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, 500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [job?.id, job?.status]);
  async function summarize(send: boolean) {
    setBusy("Starting summary…");
    setError("");
    setNotice("");
    try {
      const result = await api<{ job: Job }>(
        demo ? "/api/demo" : "/api/summaries",
        "POST",
        {
          send: demo ? false : send,
        },
      );
      setJob(result.job);
      if (result.job.run) setRun(result.job.run);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function retry() {
    if (!job) return;
    setBusy("Resuming saved summary…");
    setError("");
    try {
      const result = await api<{ job: Job }>(
        `/api/jobs/${job.id}/retry`,
        "POST",
        {},
      );
      setJob(result.job);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function sendSaved() {
    if (!run) return;
    setBusy("Sending saved summaries…");
    setError("");
    try {
      setRun(await api<Run>(`/api/runs/${run.id}/send`, "POST", {}));
      setNotice(
        "Check each module’s delivery status below. Successful modules are not resent.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <main>
      <header>
        <div className="brand">MATIKS</div>
        <div className="divider" />
        <h1>{demo ? "Feature requests · Quick demo" : "Feature requests"}</h1>
        <button
          className="outline refresh"
          onClick={() => void load(true)}
          disabled={working}
        >
          <Icon type="refresh" />
          {demo ? "Reload sample" : "Refresh reports"}
        </button>
      </header>
      <div className="toolbar">
        <label className="search">
          <Icon type="search" />
          <input
            aria-label="Search feature requests"
            placeholder="Search feature requests…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Filter by module"
          value={moduleFilter}
          onChange={(e) => setModuleFilter(e.target.value)}
        >
          <option value="">All modules</option>
          {config.modules.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        <button
          className="primary"
          disabled={
            working ||
            dirty ||
            (!demo && !credentials.slack) ||
            !credentials.openrouter ||
            !tickets.length
          }
          onClick={() => void summarize(!demo)}
        >
          <Icon type="send" />
          {demo ? "Preview demo" : "Summarize and send"}
        </button>
        <p className="search-hint">
          {demo
            ? "Preview only: latest 20 suggestions from the cached complete snapshot. No Slack messages are sent."
            : "Search narrows the list. Summaries always cover every suggestion in ClickUp."}
        </p>
      </div>
      <div aria-live="polite" className="messages">
        {busy && <p className="status">{busy}</p>}
        {job && (
          <section className="job-progress" aria-label="Summary job progress">
            <p
              className={
                job.status === "error" || job.status === "interrupted"
                  ? "error"
                  : "status"
              }
            >
              {jobProgress(job)}
            </p>
            <small>
              {job.send ? "Summary and send" : "Preview only"} · Saved job ·
              Routing snapshot preserved
              {job.totalBatches > 0 &&
                ` · ${job.completedBatches}/${job.totalBatches} batches saved`}
            </small>
            {job.status === "summarizing" && (
              <progress
                aria-label="Completed summary batches"
                max={job.totalBatches || 1}
                value={job.completedBatches}
              />
            )}
            {["error", "interrupted"].includes(job.status) && (
              <button
                className="outline"
                disabled={working}
                onClick={() => void retry()}
              >
                Retry saved job
              </button>
            )}
          </section>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {notice && <p className="notice">{notice}</p>}
        {!demo && !credentials.slack && (
          <p className="setup">
            Slack is not connected. Add <code>SLACK_BOT_TOKEN</code> to this
            app’s private <code>.env.local</code> and restart. Preview summaries
            works without Slack.
          </p>
        )}
        {dirty && (
          <p className="setup">Save routing before creating a summary.</p>
        )}
      </div>
      <div className="columns">
        <section className="requests">
          <h2>Feature requests</h2>
          <p className="sub">
            {fetched
              ? demo
                ? `Demo sample: ${tickets.length} of ${fetched.sourceTickets || tickets.length} suggestions · Cached ${new Date(fetched.snapshotAt || fetched.fetchedAt).toLocaleString()}`
                : `${tickets.length} suggestions from all ${fetched.fetchedTasks} reports · ${fetched.pages} pages fetched`
              : "Fetching your ClickUp suggestions…"}
          </p>
          <div className="table-head">
            <span>Title</span>
            <span>Module</span>
            <span>Reported</span>
          </div>
          <div className="ticket-list">
            {filtered.map((t) => {
              const m = moduleFor(t, config);
              return (
                <button
                  className="ticket-row"
                  key={t.id}
                  onClick={() => setSelected(t)}
                >
                  <span>
                    <strong>{t.title}</strong>
                    <small>{t.body || "No description supplied."}</small>
                  </span>
                  <span>
                    <span
                      className={`tag color-${config.modules.findIndex((mod) => mod.id === m?.id) % 5}`}
                    >
                      {m?.name || "Unassigned"}
                    </span>
                  </span>
                  <time>
                    {t.createdAt
                      ? new Date(t.createdAt).toLocaleDateString("en-IN", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })
                      : "Unknown"}
                  </time>
                  <span className="chevron">›</span>
                </button>
              );
            })}
            {!busy && !filtered.length && (
              <p className="empty">
                {tickets.length
                  ? "No suggestions match these filters."
                  : "No suggestions found. Refresh after a feature request is submitted."}
              </p>
            )}
          </div>
          {fetched && (
            <p className="footnote">
              {demo ? "Cached complete snapshot" : "Last fetched"}{" "}
              {new Date(fetched.fetchedAt).toLocaleString()} ·{" "}
              {demo
                ? "Latest20 selected from the cached complete dataset; no live refresh."
                : "All dates included, open and closed."}{" "}
              Module labels here use keywords; summaries use AI grouping.
            </p>
          )}
        </section>
        <aside>
          <section className="routing">
            <h2>Module routing</h2>
            <p className="sub">
              Configure where summaries for each module should be sent.
            </p>
            <div className="routing-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Module</th>
                    <th>Keywords</th>
                    <th>Slack destination</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {config.modules.map((m, index) => (
                    <tr key={m.id}>
                      <td>
                        <input
                          aria-label={`Module ${m.id} name`}
                          value={m.name}
                          onChange={(e) =>
                            setConfig({
                              modules: config.modules.map((mod, i) =>
                                i === index
                                  ? { ...mod, name: e.target.value }
                                  : mod,
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`${m.name} keywords`}
                          value={keywordInputs[m.id] ?? m.keywords.join(", ")}
                          onChange={(e) => {
                            setKeywordInputs((previous) => ({
                              ...previous,
                              [m.id]: e.target.value,
                            }));
                            setConfig({
                              modules: config.modules.map((mod, i) =>
                                i === index
                                  ? {
                                      ...mod,
                                      keywords: e.target.value
                                        .split(",")
                                        .map((k) => k.trim())
                                        .filter(Boolean),
                                    }
                                  : mod,
                              ),
                            });
                          }}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`${m.name} Slack destination`}
                          placeholder="Channel or PM user ID"
                          value={m.destination}
                          onChange={(e) =>
                            setConfig({
                              modules: config.modules.map((mod, i) =>
                                i === index
                                  ? {
                                      ...mod,
                                      destination: e.target.value.trim(),
                                    }
                                  : mod,
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <button
                          className="remove"
                          aria-label={`Remove ${m.name}`}
                          disabled={config.modules.length < 2 || working}
                          onClick={() =>
                            setConfig({
                              modules: config.modules.filter(
                                (_, i) => i !== index,
                              ),
                            })
                          }
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="footnote">
              Use a channel ID (C…), private channel ID (G…) or PM user ID (U…).
              Invite the bot to channels. Empty destinations are shown as not
              configured.
            </p>
            <div className="routing-actions">
              <button
                className="outline"
                disabled={working || config.modules.length >= 20}
                onClick={() =>
                  setConfig({
                    modules: [
                      ...config.modules,
                      {
                        id: `module-${Date.now()}`,
                        name: "New module",
                        keywords: [],
                        destination: "",
                      },
                    ],
                  })
                }
              >
                Add module
              </button>
              <button
                className="primary"
                disabled={working || !dirty}
                onClick={save}
              >
                Save routing
              </button>
            </div>
          </section>
          <section className="summaries">
            <div className="section-heading">
              <h2>Module summaries</h2>
              <button
                className="outline"
                disabled={
                  working || dirty || !credentials.openrouter || !tickets.length
                }
                onClick={() => void summarize(false)}
              >
                {demo ? "Preview demo" : "Preview summaries"}
              </button>
            </div>
            <p className="sub">
              {demo
                ? "Preview of the latest 20 suggestions only, grouped by module."
                : "AI summaries of all feature requests, grouped by module."}
            </p>
            {!run ? (
              <p className="empty">
                Create a preview to review the summaries before sending.
              </p>
            ) : (
              <>
                <p className="coverage">
                  {demo
                    ? `Demo sample: ${run.totalTickets} of ${run.sourceTickets || fetched?.sourceTickets || run.totalTickets} suggestions covered`
                    : `All ${run.totalTickets} suggestions covered`}{" "}
                  · {run.modelCalls} model{" "}
                  {run.modelCalls === 1 ? "call" : "calls"} · Saved{" "}
                  {new Date(run.createdAt).toLocaleString()}
                </p>
                {run.summaries.map((g) => {
                  const m = run.config.modules.find(
                    (m) => m.id === g.moduleId,
                  )!;
                  const delivery = run.deliveries[g.moduleId];
                  return (
                    <article className="summary" key={g.moduleId}>
                      <div className="summary-title">
                        <h3>{m.name}</h3>
                        <span className={`delivery ${delivery.state}`}>
                          {delivery.state === "unsent"
                            ? "Not sent"
                            : delivery.state === "unconfigured"
                              ? "Not configured"
                              : delivery.state}
                        </span>
                      </div>
                      <p className="summary-text">{g.summary}</p>
                      <p className="footnote">
                        Coverage: {g.ticketIds.length} reports · Destination:{" "}
                        {delivery.destination || "Not configured"}
                      </p>
                      {delivery.error && (
                        <p className="error">{delivery.error}</p>
                      )}
                      <details>
                        <summary>View included reports</summary>
                        <div className="report-links">
                          {g.ticketIds.map((id) => (
                            <a
                              key={id}
                              href={`https://app.clickup.com/t/${encodeURIComponent(id)}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {id}
                            </a>
                          ))}
                        </div>
                      </details>
                    </article>
                  );
                })}
                {!demo && (
                  <button
                    className="primary"
                    disabled={working || !credentials.slack}
                    onClick={sendSaved}
                  >
                    Send unsent summaries
                  </button>
                )}
                <p className="footnote">
                  {demo
                    ? "Quick demo is preview only. No Slack messages are sent."
                    : "Already sent modules are skipped. Uncertain deliveries require a manual Slack check."}
                </p>
              </>
            )}
          </section>
        </aside>
      </div>
      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close outline"
              aria-label="Close report"
              onClick={() => setSelected(null)}
            >
              ×
            </button>
            <h2 id="ticket-title">{selected.title}</h2>
            <p className="sub">
              {selected.status} ·{" "}
              {selected.createdAt
                ? new Date(selected.createdAt).toLocaleString()
                : "Date unavailable"}
            </p>
            <p className="report-body">
              {selected.body || "No description supplied."}
            </p>
            <a href={selected.url} target="_blank" rel="noreferrer">
              Open in ClickUp ↗
            </a>
          </section>
        </div>
      )}
    </main>
  );
}
