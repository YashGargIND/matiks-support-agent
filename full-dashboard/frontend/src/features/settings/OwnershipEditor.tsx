import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { Field, FieldLabel, FieldGroup } from "../../components/ui/field";
import { categories, parseObject } from "../../lib/api";
export default function OwnershipEditor({
  people,
  onChange,
}: {
  people: unknown[];
  onChange: (v: unknown[]) => void;
}) {
  const update = (i: number, key: string, value: unknown) =>
    onChange(
      people.map((p, j) => (j === i ? { ...parseObject(p), [key]: value } : p)),
    );
  return (
    <>
      <h2>Team and ownership</h2>
      <p className="muted">
        Only accepted mappings filter the queue. A code path alone does not
        prove ownership.
      </p>
      {people.length === 0 ? (
        <p>
          No people are mapped yet. Add someone and assign the categories they
          review.
        </p>
      ) : null}
      {people.map((p, i) => {
        const x = parseObject(p);
        return (
          <section className="settings-group" key={i}>
            <FieldGroup>
              <Field>
                <FieldLabel>Person ID</FieldLabel>
                <Input
                  aria-label={`Person ${i + 1} ID`}
                  value={String(x.id || "")}
                  onChange={(e) => update(i, "id", e.target.value)}
                  placeholder="Short stable ID"
                />
              </Field>
              <Field>
                <FieldLabel>Name</FieldLabel>
                <Input
                  aria-label={`Person ${i + 1} name`}
                  value={String(x.name || "")}
                  onChange={(e) => update(i, "name", e.target.value)}
                  placeholder="Person's name"
                />
              </Field>
              <Field>
                <FieldLabel>GitHub handle</FieldLabel>
                <Input
                  aria-label={`Person ${i + 1} GitHub handle`}
                  value={String(x.github_handle || "")}
                  onChange={(e) =>
                    update(i, "github_handle", e.target.value || null)
                  }
                />
              </Field>
              <Field>
                <FieldLabel>Modules</FieldLabel>
                <Input
                  aria-label={`Person ${i + 1} modules`}
                  value={Array.isArray(x.modules) ? x.modules.join(", ") : ""}
                  onChange={(e) =>
                    update(
                      i,
                      "modules",
                      e.target.value
                        .split(",")
                        .map((v) => v.trim())
                        .filter(Boolean),
                    )
                  }
                  placeholder="Comma-separated module names"
                />
              </Field>
            </FieldGroup>
            <fieldset className="category-checkboxes">
              <legend>Categories</legend>
              {Object.entries(categories).map(([id, label]) => (
                <label key={id}>
                  <input
                    type="checkbox"
                    checked={
                      Array.isArray(x.categories) && x.categories.includes(id)
                    }
                    onChange={(e) =>
                      update(
                        i,
                        "categories",
                        e.target.checked
                          ? [
                              ...(Array.isArray(x.categories)
                                ? x.categories
                                : []),
                              id,
                            ]
                          : (Array.isArray(x.categories)
                              ? x.categories
                              : []
                            ).filter((v) => v !== id),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <Button
              variant="outline"
              onClick={() => onChange(people.filter((_, j) => j !== i))}
            >
              Remove person
            </Button>
          </section>
        );
      })}
      <Button
        variant="outline"
        onClick={() =>
          onChange([
            ...people,
            {
              id: "",
              name: "",
              categories: [],
              modules: [],
              github_handle: null,
            },
          ])
        }
      >
        Add person
      </Button>
      <p className="muted">
        No unreviewed owner suggestions are accepted automatically.
      </p>
    </>
  );
}
