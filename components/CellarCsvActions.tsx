"use client";

import { CsvActions, type CsvLabels } from "./CsvActions";

export type { CsvLabels } from "./CsvActions";

export function CellarCsvActions({ labels }: { labels: CsvLabels }) {
  return (
    <CsvActions
      endpoints={{
        export: "/api/cellar/export",
        template: "/api/cellar/template",
        import: "/api/cellar/import",
      }}
      labels={labels}
    />
  );
}
