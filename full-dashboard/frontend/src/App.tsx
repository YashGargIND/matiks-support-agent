import { useState, useRef, useEffect, lazy, Suspense } from "react";
import {
  NavLink,
  Link,
  Routes,
  Route,
  useSearchParams,
  useLocation,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Inbox as InboxIcon,
  Layers,
  ChartNoAxesColumn,
  History,
  Settings as SettingsIcon,
  LockKeyhole,
  Search,
  HelpCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "./components/ui/dialog";
import { loadOverview, loadProblems, reportSummary } from "./lib/api";
import Inbox from "./features/Inbox";
import PageBoundary from "./components/PageBoundary";
import { Loading } from "./components/shared";
const Problems = lazy(() => import("./features/Problems"));
const Insights = lazy(() => import("./features/Insights"));
const Activity = lazy(() => import("./features/Activity"));
const HowItWorks = lazy(() => import("./features/HowItWorks"));
const Settings = lazy(() => import("./features/Settings"));
const nav = [
  ["/", "Inbox", InboxIcon],
  ["/problems", "Problems", Layers],
  ["/insights", "Insights", ChartNoAxesColumn],
  ["/activity", "Activity", History],
  ["/settings", "Settings", SettingsIcon],
] as const;
const views = [
  ["Safety", "dm_safety"],
  ["Payments", "purchase"],
  ["Streaks", "streak"],
  ["Merch", "merch"],
  ["Bugs", "bugs"],
  ["VIP only", "vip"],
];
export default function App() {
  const [params, setParams] = useSearchParams();
  const [collapsed, setCollapsed] = useState(false);
  const [safe, setSafe] = useState(false);
  const [help, setHelp] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const search = useRef<HTMLInputElement>(null);
  const routeLocation = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [routeLocation.pathname]);
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
        search.current?.focus();
      }
      if (e.key === "?") setHelp(true);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const q = useQuery({
    queryKey: ["overview", params.get("provenance") || "real"],
    queryFn: () =>
      loadOverview(
        params.get("provenance") === "synthetic" ? "synthetic" : "real",
      ),
    refetchInterval: 15000,
  });
  const person = params.get("person") || "everyone";
  const searchTerm = (params.get("search") || "").trim().toLowerCase();
  const problemSearch = useQuery({
    queryKey: ["problems", person, params.get("provenance")],
    queryFn: () =>
      loadProblems(
        person,
        params.get("provenance") === "synthetic" ? "synthetic" : "real",
      ),
    enabled: searchTerm.length >= 2,
  });
  const matchingReports = (q.data?.tickets || [])
    .filter(
      (t) =>
        (person === "everyone" || t.assigned_to === person) &&
        [t.subject, t.body, t.user_identifier, t.internal_summary]
          .join(" ")
          .toLowerCase()
          .includes(searchTerm),
    )
    .slice(0, 4);
  const matchingProblems = (problemSearch.data || [])
    .filter((p) =>
      [p.title, p.summary, p.owner]
        .join(" ")
        .toLowerCase()
        .includes(searchTerm),
    )
    .slice(0, 4);
  const update = (key: string, value: string) => {
    setParams((p) => {
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });
  };
  return (
    <div className={collapsed ? "app-shell sidebar-collapsed" : "app-shell"}>
      <aside className="sidebar">
        <Link to="/" aria-label="Matiks Support home" className="brand">
          <img src="/matiks-logo.svg" alt="Matiks" />
          <span>Support</span>
        </Link>
        <Button
          variant="ghost"
          size="icon-sm"
          className="nav-collapse"
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
        <nav aria-label="Main navigation">
          {nav.map(([path, label, Icon]) => (
            <NavLink
              to={`${path}?person=${person}`}
              key={path}
              aria-label={label}
              end={path === "/"}
              className={({ isActive }) =>
                isActive ? "nav-item active" : "nav-item"
              }
            >
              <Icon />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="saved-views">
          <p>Saved views</p>
          {(!q.data?.saved_views?.length ? views : []).map(([name, value]) => (
            <Link
              key={name}
              to={`/?${value === "vip" ? "cohort=vip" : `category=${value}`}&person=${person}`}
            >
              {name}
            </Link>
          ))}
          {q.data?.saved_views?.map((v) => (
            <Link
              key={v.id}
              to={`/?${new URLSearchParams(Object.fromEntries(Object.entries(v.filters || {}).map(([k, v]) => [k, String(v)])))}`}
            >
              {v.name}
            </Link>
          ))}
        </div>
        <div className="sidebar-bottom">
          <NavLink
            to={`/how-it-works?person=${person}`}
            className="nav-item"
            aria-label="How it works"
          >
            <HelpCircle />
            <span>How it works</span>
          </NavLink>
          <Button variant="ghost" onClick={() => setHelp(true)}>
            Keyboard shortcuts <kbd>?</kbd>
          </Button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <label className="viewing">
            Viewing as
            <select
              aria-label="Viewing as"
              value={person}
              onChange={(e) => update("person", e.target.value)}
            >
              <option value="everyone">Everyone</option>
              {q.data?.people?.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <div className="global-search">
            <Search />
            <Input
              ref={search}
              aria-label="Search tickets, users, or problems"
              placeholder="Search tickets, users, or problems"
              value={params.get("search") || ""}
              onFocus={() => setSearchOpen(true)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setSearchOpen(false);
              }}
              onChange={(e) => {
                setSearchOpen(true);
                update("search", e.target.value);
              }}
            />
            <kbd>/</kbd>
            {searchOpen && searchTerm.length >= 2 ? (
              <div className="search-results" aria-label="Search results">
                <div className="search-results-heading">
                  <strong>Search results</strong>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSearchOpen(false)}
                  >
                    Close results
                  </Button>
                </div>
                <small>Reports and users</small>
                {matchingReports.map((t) => (
                  <Link
                    key={t.id}
                    onClick={() => setSearchOpen(false)}
                    to={`/?ticket=${t.id}&person=${person}&provenance=${t.provenance}&status=all`}
                  >
                    <strong>
                      {t.category === "dm_safety"
                        ? "Safety report requires individual review"
                        : reportSummary(t)}
                    </strong>
                    <small>{t.user_identifier || "User redacted"}</small>
                  </Link>
                ))}
                {!matchingReports.length ? <p>No matching reports</p> : null}
                <small>Problems</small>
                {matchingProblems.map((p) => (
                  <Link
                    key={p.id}
                    onClick={() => setSearchOpen(false)}
                    to={`/problems/${p.id}?person=${person}&provenance=${params.get("provenance") || "real"}`}
                  >
                    <strong>{p.title}</strong>
                    <small>{p.ticket_count} reports</small>
                  </Link>
                ))}
                {problemSearch.isPending ? (
                  <p>Checking problems…</p>
                ) : problemSearch.error ? (
                  <p>Problem search unavailable. Open Problems to retry.</p>
                ) : !matchingProblems.length ? (
                  <p>No matching problems</p>
                ) : null}
              </div>
            ) : null}
          </div>
          <Button
            className="safe-pill"
            variant="secondary"
            onClick={() => setSafe(true)}
          >
            <LockKeyhole data-icon="inline-start" />
            Safe mode on
          </Button>
        </header>
        <PageBoundary key={routeLocation.pathname}>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route
                path="/"
                element={
                  <Inbox
                    overview={q}
                    onHelp={() => setHelp(true)}
                    searchRef={search}
                  />
                }
              />
              <Route path="/problems" element={<Problems />} />
              <Route path="/problems/:id" element={<Problems />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/how-it-works" element={<HowItWorks />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Suspense>
        </PageBoundary>
      </div>
      <Dialog open={safe} onOpenChange={setSafe}>
        <DialogContent>
          <DialogTitle>Safe mode is always on</DialogTitle>
          <DialogDescription>
            Nothing is sent to users or changed in real systems. Approved
            replies and actions stay in the local outbox for review.
          </DialogDescription>
          <Link to="/settings?section=safety" onClick={() => setSafe(false)}>
            See how safe mode is enforced
          </Link>
        </DialogContent>
      </Dialog>
      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>
            Use these while reviewing the inbox. Shortcuts pause while you type.
          </DialogDescription>
          <dl className="shortcut-list">
            {[
              ["J / K", "Next / previous ticket"],
              ["A", "Review approval"],
              ["E", "Edit reply"],
              ["P", "Send to a person"],
              ["/", "Search"],
              ["Esc", "Close ticket panel"],
              ["?", "Show this help"],
            ].map(([key, text]) => (
              <div key={key}>
                <dt>
                  <kbd>{key}</kbd>
                </dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </div>
  );
}
