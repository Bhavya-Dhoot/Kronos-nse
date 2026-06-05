import type { MVSData } from "../types/variance";

interface FearPanicBannerProps {
  mvsData: MVSData | null;
}

export default function FearPanicBanner({ mvsData }: FearPanicBannerProps) {
  const isFearPanic = mvsData?.market_state === "panic" || mvsData?.market_state === "fear";

  if (!isFearPanic) return null;

  const isPanic = mvsData?.market_state === "panic";

  return (
    <div
      style={{
        position: "sticky" as const,
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        background: isPanic ? "#7f1d1d" : "#9a3412",
        color: "#fecaca",
        textAlign: "center",
        padding: "6px 12px",
        fontWeight: 700,
        fontSize: "0.85rem",
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        borderBottom: `2px solid ${isPanic ? "#dc2626" : "#ea580c"}`,
      }}
    >
      {isPanic ? "⚠ PANIC — HIGH VOLATILITY" : "⚠ FEAR — HIGH VOLATILITY"}
    </div>
  );
}
