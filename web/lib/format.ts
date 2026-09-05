import type { Action } from "./types";
export function dateLabel(
  value: string | null | undefined,
  status = "verified",
): string {
  if (!value || status !== "verified" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
    return "Unknown date";
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== value)
    return "Unknown date";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
export function stateLabel(state: string): string {
  return (
    (
      {
        unknown: "Unknown · review needed",
        in_progress: "In progress",
      } as Record<string, string>
    )[state] || state.charAt(0).toUpperCase() + state.slice(1)
  );
}
export function kindLabel(kind: string): string {
  return kind === "action_item" ? "Action" : kind;
}
export function filterActions(actions: Action[], tab: string): Action[] {
  return actions.filter((a) =>
    tab === "unresolved"
      ? a.unresolved
      : tab === "completed"
        ? a.state === "completed"
        : a.state === "cancelled",
  );
}
export function sizeLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${Math.ceil(bytes / 1024)} KB`;
}
