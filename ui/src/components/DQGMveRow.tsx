import { useVarianceWS } from "../hooks/useVarianceWS";

export default function DQGMveRow() {
  const { mvsData, connected } = useVarianceWS();

  // Compute active dimension count (non-stale dimensions)
  const activeDims = mvsData?.dimensions?.filter((d) => !d.is_stale).length ?? 0;
  const totalDims = mvsData?.dimensions?.length ?? 6;
  const composite = mvsData?.composite ?? null;
  const marketState = mvsData?.market_state ?? null;

  // Relative time helper
  const timeAgo = mvsData?.created_at
    ? (() => {
        const diff = Date.now() - new Date(mvsData.created_at).getTime();
        const s = Math.floor(diff / 1000);
        if (s < 5) return "just now";
        if (s < 60) return `${s}s ago`;
        const m = Math.floor(s / 60);
        return `${m}m ago`;
      })()
    : "—";

  const stateColors: Record<string, string> = {
    panic: "#dc2626",
    fear: "#ea580c",
    uncertain: "#d97706",
    bull_run: "#16a34a",
    neutral: "#6b7280",
  };

  const compColor = composite !== null
    ? composite > 0.2
      ? "#16a34a"
      : composite < -0.2
        ? "#dc2626"
        : "#d97706"
    : "#6b7280";

  const rowStyle = {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "6px 12px",
    fontSize: "0.8rem",
    fontFamily: "monospace",
    background: "#1a1a2e",
    borderRadius: 4,
    border: "1px solid #2a2a3e",
  };

  return (
    <div style={rowStyle}>
      <span style={{ color: "#888" }}>MVE</span>

      {/* Active dimensions badge */}
      <span
        style={{
          background: connected ? "#1e3a5f" : "#3a1a1a",
          color: connected ? "#93c5fd" : "#fca5a5",
          padding: "2px 6px",
          borderRadius: 4,
          fontWeight: 600,
          fontSize: "0.75rem",
        }}
      >
        {activeDims}/{totalDims} active
      </span>

      {/* Composite score */}
      {composite !== null && (
        <span style={{ color: compColor, fontWeight: 600 }}>
          MVS {composite >= 0 ? "+" : ""}{composite.toFixed(2)}
        </span>
      )}

      {/* Market state badge */}
      {marketState && (
        <span
          style={{
            background: stateColors[marketState] + "22",
            color: stateColors[marketState],
            padding: "2px 6px",
            borderRadius: 4,
            fontWeight: 600,
            fontSize: "0.75rem",
            textTransform: "uppercase",
            border: `1px solid ${stateColors[marketState]}`,
          }}
        >
          {marketState}
        </span>
      )}

      {/* Last update time */}
      <span style={{ color: "#666", marginLeft: "auto" }}>{timeAgo}</span>
    </div>
  );
}
