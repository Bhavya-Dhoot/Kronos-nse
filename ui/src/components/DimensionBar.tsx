interface DimensionBarProps {
  name: string;
  score: number;
  weight: number;
  is_stale: boolean;
}

function formatScore(value: number): string {
  return value > 0 ? `+${value.toFixed(2)}` : value.toFixed(2);
}

function scoreColor(value: number): string {
  if (value > 0) return "#16a34a";
  if (value < 0) return "#dc2626";
  return "#6b7280";
}

export default function DimensionBar({
  name,
  score,
  weight,
  is_stale,
}: DimensionBarProps) {
  const barWidth = Math.abs(score) * 100;
  const color = scoreColor(score);

  return (
    <div
      style={{
        opacity: is_stale ? 0.5 : 1,
        transition: "opacity 0.3s",
      }}
    >
      {/* Label row */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 4,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 12,
              color: "#c0c0c0",
              fontWeight: 500,
            }}
          >
            {name}
          </span>
          {is_stale && (
            <span
              style={{
                fontSize: 9,
                color: "#9ca3af",
                backgroundColor: "#2a2a3e",
                padding: "0 5px",
                borderRadius: 4,
                lineHeight: "14px",
              }}
            >
              stale
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color,
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {formatScore(score)}
          </span>
          <span
            style={{
              fontSize: 9,
              color: "#9ca3af",
              backgroundColor: "#2a2a3e",
              padding: "0 6px",
              borderRadius: 4,
              lineHeight: "14px",
            }}
          >
            {weight.toFixed(1)}x
          </span>
        </div>
      </div>

      {/* Bar track */}
      <div
        style={{
          height: 8,
          width: "100%",
          backgroundColor: "#2a2a3e",
          borderRadius: 4,
          overflow: "hidden",
        }}
      >
        {/* Bar fill */}
        <div
          style={{
            height: "100%",
            width: `${Math.min(barWidth, 100)}%`,
            backgroundColor: color,
            borderRadius: 4,
            transition: "width 0.4s ease, background-color 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}
