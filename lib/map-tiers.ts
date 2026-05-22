export const DEFAULT_TIERS = ["1", "2"];

export const TIER_DEFS = [
  { key: "1", label: "T1", color: "#FFD166", desc: "Iconic" },
  { key: "2", label: "T2", color: "#FF5C8A", desc: "Premier" },
  { key: "3", label: "T3", color: "#6FFFE9", desc: "Solid" },
  { key: "4", label: "T4", color: "#B5965D", desc: "Standard" },
  { key: "5", label: "T5", color: "#7C6F9F", desc: "Entry" },
  { key: "null", label: "—", color: "#5A5270", desc: "Untiered" },
] as const;
