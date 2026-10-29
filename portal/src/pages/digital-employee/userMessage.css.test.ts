import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const stylesheet = readFileSync(
  new URL("../digital-employee.css", import.meta.url),
  "utf8",
);

test("user message paragraphs and list items preserve typed line breaks", () => {
  assert.match(
    stylesheet,
    /\.portal-digital-employee \.message\.user \.portal-x-markdown p,\s*\.portal-digital-employee \.message\.user \.portal-x-markdown li\s*\{\s*white-space:\s*pre-wrap;\s*overflow-wrap:\s*anywhere;\s*\}/,
  );
});
