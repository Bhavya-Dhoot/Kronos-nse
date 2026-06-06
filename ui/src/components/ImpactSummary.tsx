interface ImpactSummaryProps {
  temperature_adjustment: number;
  directional_bias: number;
  band_width_multiplier: number;
  signal_threshold: number;
  confidence_override: string | null;
}

function valueColor(value: number): string {
  if (value > 0) return "#16a34a";
  if (value < 0) return "#dc2626";
  return "#e0e0e0";
}

function formatValue(value: number): string {
  return value > 0 ? `+${value.toFixed(4)}` : value.toFixed(4);
}

const ROWS: {
  label: string;
  key: keyof ImpactSummaryProps;
  format: "number" | "string";
}[] = [
  { label: "Temp Adj", key: "temperature_adjustment", format: "number" },
  { label: "Dir Bias", key: "directional_bias", format: "number" },
  { label: "Band Mult", key: "band_width_multiplier", format: "number" },
  { label: "Signal Thresh", key: "signal_threshold", format: "number" },
  { label: "Conf Override", key: "confidence_override", format: "string" },
];

export default function ImpactSummary(props: ImpactSummaryProps) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: "2px 12px",
        fontSize: 12,
      }}
    >
      {ROWS.map((row) => {
        const value = props[row.key];
        return (
          <div key={row.key} style={{ display: "contents" }}>
            <span style={{ color: "#9ca3af", whiteSpace: "nowrap" }}>
              {row.label}
            </span>
            {row.format === "number" ? (
              <span
                style={{
                  color: valueColor(value as number),
                  fontFamily: "ui-monospace, monospace",
                  fontWeight: 600,
                  textAlign: "right",
                }}
              >
                {formatValue(value as number)}
              </span>
            ) : (
              <span
                style={{
                  color: value ? "#d97706" : "#6b7280",
                  fontFamily: "ui-monospace, monospace",
                  fontWeight: 600,
                  textAlign: "right",
                  fontSize: 10,
                }}
              >
                {value || "none"}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
