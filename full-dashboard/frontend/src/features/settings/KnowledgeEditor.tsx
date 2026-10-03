import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { loadKnowledge, patch, categories, parseObject } from "../../lib/api";
import {
  Loading,
  Failure,
  SelectField,
  Technical,
} from "../../components/shared";
import { Field, FieldLabel, FieldGroup } from "../../components/ui/field";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
interface Knowledge {
  facts: Record<string, unknown>[];
  fingerprint: string;
}
export default function KnowledgeEditor({
  reviewer,
  setReviewer,
}: {
  reviewer: string;
  setReviewer: (v: string) => void;
}) {
  const q = useQuery({
    queryKey: ["knowledge"],
    queryFn: async () => (await loadKnowledge()) as Knowledge,
  });
  const [local, setLocal] = useState<Record<string, unknown>[] | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const client = useQueryClient();
  const facts = local ?? q.data?.facts ?? [];
  const dirty =
    local !== null && JSON.stringify(local) !== JSON.stringify(q.data?.facts);
  useEffect(() => {
    if (!dirty) return;
    const leave = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const navigate = (e: MouseEvent) => {
      const target = (e.target as HTMLElement)?.closest("a,button");
      if (
        target?.closest("nav") &&
        !window.confirm("Leave Knowledge with unsaved changes?")
      ) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", leave);
    document.addEventListener("click", navigate, true);
    return () => {
      window.removeEventListener("beforeunload", leave);
      document.removeEventListener("click", navigate, true);
    };
  }, [dirty]);
  const update = (i: number, key: string, value: unknown) => {
    setReviewed(false);
    setLocal(facts.map((f, j) => (i === j ? { ...f, [key]: value } : f)));
  };
  if (q.isPending) return <Loading />;
  if (q.error) return <Failure error={q.error} retry={() => q.refetch()} />;
  return (
    <>
      <h2>Knowledge</h2>
      <p className="muted">
        Verified answers need an approved source, checked date, category, and
        exact wording. Unverified entries cannot support AI-resolved replies.
      </p>
      {facts.length === 0 ? (
        <p>
          No facts have been entered. Add an unverified entry and check it
          against an approved source before verification.
        </p>
      ) : null}
      {facts.map((f, i) => (
        <section className="settings-group" key={i}>
          <div className="section-heading">
            <h3>{String(f.topic || f.id || "New knowledge entry")}</h3>
            <Badge variant="secondary">
              {f.status === "verified" ? "Verified" : "Unverified"}
            </Badge>
          </div>
          <FieldGroup>
            <Field>
              <FieldLabel>Entry ID</FieldLabel>
              <Input
                aria-label={`Entry ${i + 1} id`}
                value={String(f.id || "")}
                onChange={(e) => update(i, "id", e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel>Topic</FieldLabel>
              <Input
                aria-label={`Entry ${i + 1} topic`}
                value={String(f.topic || "")}
                onChange={(e) => update(i, "topic", e.target.value)}
              />
            </Field>
            <SelectField
              label="Category"
              value={String(f.category || "other")}
              onChange={(v) => update(i, "category", v)}
              options={Object.entries(categories).map(([value, label]) => ({
                value,
                label,
              }))}
            />
            <SelectField
              label="Verification status"
              value={String(f.status || "unverified")}
              onChange={(v) => update(i, "status", v)}
              options={[
                { value: "unverified", label: "Unverified" },
                { value: "verified", label: "Verified" },
              ]}
            />
            <Field>
              <FieldLabel>Approved source</FieldLabel>
              <Input
                aria-label={`Entry ${i + 1} source`}
                value={String(f.source || "")}
                onChange={(e) => update(i, "source", e.target.value)}
                placeholder="Approved policy or source reference"
              />
            </Field>
            <Field>
              <FieldLabel>Checked at (with timezone)</FieldLabel>
              <Input
                aria-label={`Entry ${i + 1} checked at`}
                value={String(f.checked_at || "")}
                onChange={(e) => update(i, "checked_at", e.target.value)}
                placeholder="2026-10-03T12:00:00+00:00"
              />
            </Field>
          </FieldGroup>
          {[
            ["en", "English"],
            ["hi", "Hindi"],
            ["hinglish", "Hinglish"],
          ].map(([lang, label]) => (
            <Field key={lang}>
              <FieldLabel>{label} approved reply</FieldLabel>
              <Textarea
                rows={3}
                aria-label={`${label} approved reply for entry ${i + 1}`}
                value={String(parseObject(f.answers)[lang] || "")}
                onChange={(e) =>
                  update(i, "answers", {
                    ...parseObject(f.answers),
                    [lang]: e.target.value,
                  })
                }
              />
            </Field>
          ))}
          <Technical title="Structured policy values">
            <pre>{JSON.stringify(f.values || {}, null, 2)}</pre>
            <Field>
              <FieldLabel>Policy values JSON</FieldLabel>
              <JsonEditor
                value={f.values || {}}
                onChange={(v) => update(i, "values", v)}
              />
            </Field>
          </Technical>
          <Button
            variant="outline"
            onClick={() => setLocal(facts.filter((_, j) => j !== i))}
          >
            Remove entry
          </Button>
        </section>
      ))}
      <Button
        variant="outline"
        onClick={() =>
          setLocal([
            ...facts,
            {
              id: "",
              category: "other",
              topic: "",
              status: "unverified",
              source: "",
              checked_at: new Date().toISOString(),
              answers: { en: "" },
              values: {},
            },
          ])
        }
      >
        Add unverified entry
      </Button>
      {local ? (
        <>
          <label className="check-label">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            I reviewed the source and wording of each changed entry
          </label>
          <Field>
            <FieldLabel>Your name</FieldLabel>
            <Input
              aria-label="Knowledge reviewer"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </Field>
          <div className="inline-actions">
            <Button
              disabled={!reviewed || !reviewer.trim() || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await patch<Knowledge>("/ui/knowledge", {
                    facts: local,
                    fingerprint: q.data.fingerprint,
                    reviewer,
                  });
                  client.setQueryData(["knowledge"], result);
                  setLocal(null);
                  setReviewed(false);
                  toast.success(
                    "Knowledge saved. Verification rules still apply.",
                  );
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Save knowledge
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setLocal(null);
                setReviewed(false);
              }}
            >
              Discard changes
            </Button>
          </div>
        </>
      ) : null}
    </>
  );
}
function JsonEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState(false);
  return (
    <>
      <Textarea
        aria-label="Structured policy values JSON"
        rows={5}
        value={text}
        aria-invalid={error}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
            setError(false);
          } catch {
            setError(true);
          }
        }}
      />
      {error ? <small role="alert">Use valid JSON before saving.</small> : null}
    </>
  );
}
