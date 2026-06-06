import type { MarketState } from "../types/variance";

interface StateBadgeProps {
  state: MarketState;
}

const STATE_COLORS: Record<MarketState, string> = {
  panic: "#dc2626",
  fear: "#ea580c",
  uncertain: "#d97706",
  bull_run: "#16a34a",
  neutral: "#6b7280",
};

const STATE_LABELS: Record<MarketState, string> = {
  panic: "PANIC",
  fear: "FEAR",
  uncertain: "UNCERTAIN",
  bull_run: "BULL RUN",
  neutral: "NEUTRAL",
};

export default function StateBadge({ state }: StateBadgeProps) {
  const color = STATE_COLORS[state] ?? "#6b7280";
  const label = STATE_LABELS[state] ?? state;

  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.5px",
        color: "#fff",
        backgroundColor: color,
        textTransform: "uppercase",
        lineHeight: "20px",
      }}
    >
      {label}
    </span>
  );
}
