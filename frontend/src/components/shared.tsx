import { Link } from "react-router-dom";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "./ui/button";
import { Alert, AlertTitle, AlertDescription } from "./ui/alert";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "./ui/empty";
import { Skeleton } from "./ui/skeleton";
import { Field, FieldLabel } from "./ui/field";
import type { ReactNode } from "react";
export function Loading() {
  return (
    <div className="loading" aria-label="Loading reports">
      <Skeleton className="h-7 w-40" />
      {[0, 1, 2, 3, 4].map((n) => (
        <Skeleton key={n} className="h-16 w-full" />
      ))}
    </div>
  );
}
export function Failure({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <Alert>
      <AlertTriangle />
      <AlertTitle>Can't load this view</AlertTitle>
      <AlertDescription>
        {error.message}
        <p>
          Navigation and safe-mode information still work. Check data sources in Settings or restart the local support service.
        </p>
        <div className="inline-actions">
          <Button variant="outline" onClick={retry}>
            <RefreshCw data-icon="inline-start" />
            Try again
          </Button>
          <Link to="/settings?section=sources">Open data sources</Link>
        </div>
      </AlertDescription>
    </Alert>
  );
}
export function NoItems({
  title = "No tickets need you right now.",
  description = "Problems shows what's affecting the most users.",
  children,
}: {
  title?: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <Empty>
      <EmptyHeader>
        <Inbox />
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {children}
    </Empty>
  );
}
export function SelectField({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <Field className="select-field">
      <FieldLabel>{label}</FieldLabel>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
export function Technical({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <details className="technical">
      <summary>{title}</summary>
      {children}
    </details>
  );
}
