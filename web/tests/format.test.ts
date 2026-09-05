import test from "node:test";
import assert from "node:assert/strict";
import {
  dateLabel,
  filterActions,
  kindLabel,
  sizeLabel,
  stateLabel,
} from "../lib/format";
import type { Action } from "../lib/types";
test("unknown or unverified dates never appear verified", () => {
  assert.equal(dateLabel(null), "Unknown date");
  assert.equal(dateLabel("2026-09-03", "unverified"), "Unknown date");
  assert.equal(dateLabel("2026-02-30"), "Unknown date");
  assert.equal(dateLabel("Sunday"), "Unknown date");
});
test("verified date formatting is timezone independent", () => {
  assert.equal(dateLabel("2026-09-03"), "3 Sept 2026");
});
test("unknown actions follow backend unresolved flag; cancelled and completed stay separate", () => {
  const actions = [
    { state: "unknown", unresolved: true },
    { state: "completed", unresolved: false },
    { state: "cancelled", unresolved: false },
  ] as Action[];
  assert.deepEqual(filterActions(actions, "unresolved"), [actions[0]]);
  assert.deepEqual(filterActions(actions, "completed"), [actions[1]]);
  assert.deepEqual(filterActions(actions, "cancelled"), [actions[2]]);
});
test("friendly labels preserve action uncertainty", () => {
  assert.equal(stateLabel("unknown"), "Unknown · review needed");
  assert.equal(kindLabel("action_item"), "Action");
  assert.equal(sizeLabel(2048), "2 KB");
});
