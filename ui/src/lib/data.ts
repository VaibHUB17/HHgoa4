import { readdirSync, readFileSync, existsSync } from "fs";
import path from "path";
import type { CaseAnswer } from "./types";

// README's answer files land in `cases/` at the repo root (sibling of `ui/`), one JSON
// file per case, named `<case_id>.json`. That folder doesn't exist yet — another agent
// generates it. Until it does, fall back to the three fixtures shipped in `ui/fixtures/`.
// `source` tells the UI which one it got, so a fixture demo is never mistaken for real data.

const CASES_DIR = path.join(process.cwd(), "..", "cases");
const FIXTURES_DIR = path.join(process.cwd(), "fixtures");

export type DataSource = "real" | "fixture";

export interface LoadedCases {
  cases: CaseAnswer[];
  source: DataSource;
}

function readJsonDir(dir: string): CaseAnswer[] {
  const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
  return files
    .map((f) => JSON.parse(readFileSync(path.join(dir, f), "utf-8")) as CaseAnswer)
    .sort((a, b) => a.case_id.localeCompare(b.case_id));
}

export function loadCases(): LoadedCases {
  if (existsSync(CASES_DIR)) {
    const real = readJsonDir(CASES_DIR);
    if (real.length > 0) return { cases: real, source: "real" };
  }
  return { cases: readJsonDir(FIXTURES_DIR), source: "fixture" };
}

export function loadCase(caseId: string): { case: CaseAnswer | null; source: DataSource } {
  const { cases, source } = loadCases();
  return { case: cases.find((c) => c.case_id === caseId) ?? null, source };
}
