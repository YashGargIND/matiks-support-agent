import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createReport,
  createDemo,
  categories,
  type Category,
} from "../lib/api";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "../components/ui/dialog";
import { Field, FieldLabel, FieldGroup } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Button } from "../components/ui/button";
import { SelectField } from "../components/shared";
export default function NewReport({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (id: string, provenance: string) => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("en");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  const [scenario, setScenario] = useState("custom");
  const client = useQueryClient();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>New support report</DialogTitle>
        <DialogDescription>
          Create a report in the local queue. Personal details are redacted, and
          safe mode prevents messages or changes in real systems.
        </DialogDescription>
        <label className="check-label">
          <input
            type="checkbox"
            checked={demo}
            onChange={(e) => setDemo(e.target.checked)}
          />
          Demo example — exclude from real metrics
        </label>
        {demo ? (
          <>
            <SelectField
              label="Demo scenario"
              value={scenario}
              onChange={setScenario}
              options={[
                { value: "custom", label: "Write a custom example" },
                { value: "dm-safety", label: "DM safety: review evidence" },
                {
                  value: "dm-critical",
                  label: "DM safety: immediate escalation",
                },
                {
                  value: "merch-reply",
                  label: "Merch: historical delivery reply",
                },
                { value: "merch-delayed", label: "Merch: delayed delivery" },
                { value: "streak-restore", label: "Streak: suggested restore" },
                { value: "streak-paid", label: "Streak: paid restore offer" },
                {
                  value: "streak-unclear",
                  label: "Streak: incomplete evidence",
                },
                { value: "feature-request", label: "Feature: capture demand" },
              ]}
            />
            <small className="muted">
              Preset scenarios use explicitly synthetic local evidence. They do
              not prove live source coverage.
            </small>
          </>
        ) : null}
        <FieldGroup>
          {!demo || scenario === "custom" ? (
            <>
              <Field>
                <FieldLabel htmlFor="new-subject">What happened?</FieldLabel>
                <Input
                  id="new-subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="A short summary"
                  maxLength={1000}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="new-body">Original message</FieldLabel>
                <Textarea
                  id="new-body"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={5}
                  placeholder="Paste the report to investigate"
                  maxLength={100000}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="new-identifier">
                  Matiks username or email (optional)
                </FieldLabel>
                <Input
                  id="new-identifier"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="Used only for a read-only account match"
                />
              </Field>
              <div className="inline-actions">
                <SelectField
                  label="Category"
                  value={category}
                  onChange={setCategory}
                  options={[
                    { value: "", label: "Detect automatically" },
                    ...Object.entries(categories).map(([value, label]) => ({
                      value,
                      label,
                    })),
                  ]}
                />
                <SelectField
                  label="Language"
                  value={language}
                  onChange={setLanguage}
                  options={[
                    { value: "en", label: "English" },
                    { value: "hi", label: "Hindi" },
                    { value: "hinglish", label: "Hinglish" },
                  ]}
                />
              </div>
            </>
          ) : null}
          <Field>
            <FieldLabel htmlFor="new-reviewer">Your name</FieldLabel>
            <Input
              id="new-reviewer"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="Recorded in the local history"
            />
          </Field>
        </FieldGroup>
        <small className="muted">
          Safety rules still apply even if a different category is selected.
        </small>
        <Button
          disabled={
            ((!demo || scenario === "custom") && !body.trim()) ||
            !reviewer.trim() ||
            busy
          }
          onClick={async () => {
            setBusy(true);
            try {
              const t =
                demo && scenario !== "custom"
                  ? await createDemo(scenario, { reviewer })
                  : await createReport({
                      subject,
                      body,
                      user_identifier: identifier,
                      language: language as "en" | "hi" | "hinglish",
                      reviewer,
                      provenance: demo ? "synthetic" : "real",
                      ...(category ? { category: category as Category } : {}),
                    });
              await client.invalidateQueries({ queryKey: ["overview"] });
              onOpenChange(false);
              onCreated(t.id, demo ? "synthetic" : "real");
              setSubject("");
              setBody("");
              setIdentifier("");
              toast.success(
                "Report added. Review the investigation in the ticket panel.",
              );
            } catch (e) {
              toast.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {demo ? "Create demo report" : "Create report"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
