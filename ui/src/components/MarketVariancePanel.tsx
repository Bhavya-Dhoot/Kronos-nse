import { useMemo } from "react";
import { useVarianceWS } from "../hooks/useVarianceWS";
import MVSGauge from "./MVSGauge";
import StateBadge from "./StateBadge";
import DimensionBar from "./DimensionBar";
import ImpactSummary from "./ImpactSummary";
import type { MVSData } from "../types/variance";

function relativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 0) return "0s ago";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  return `${Math.floor(diffMin / 60)}h ago`;
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        backgroundColor: connected ? "#16a34a" : "#dc2626",
        transition: "background-color 0.3s",
      }}
      title={connected ? "Connected" : "Disconnected"}
    />
  );
}

function LoadingSkeleton() {
  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Gauge skeleton */}
      <div
        style={{
          width: 160,
          height: 100,
          margin: "0 auto",
          borderRadius: 8,
          background: "linear-gradient(90deg, #1a1a2e 25%, #2a2a3e 50%, #1a1a2e 75%)",
          backgroundSize: "200% 100%",
          animation: "shimmer 1.5s infinite",
        }}
      />
      {/* Bar skeletons */}
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div
            style={{
              height: 10,
              width: "100%",
              borderRadius: 4,
              background:
                "linear-gradient(90deg, #1a1a2e 25%, #2a2a3e 50%, #1a1a2e 75%)",
              backgroundSize: "200% 100%",
              animation: "shimmer 1.5s infinite",
              animationDelay: `${i * 0.15}s`,
            }}
          />
          <div
            style={{
              height: 8,
              width: "60%",
              borderRadius: 4,
              background:
                "linear-gradient(90deg, #1a1a2e 25%, #2a2a3e 50%, #1a1a2e 75%)",
              backgroundSize: "200% 100%",
              animation: "shimmer 1.5s infinite",
              animationDelay: `${i * 0.15 + 0.1}s`,
            }}
          />
        </div>
      ))}
      {/* Impact skeleton */}
      <div
        style={{
          height: 60,
          width: "100%",
          borderRadius: 4,
          background: "linear-gradient(90deg, #1a1a2e 25%, #2a2a3e 50%, #1a1a2e 75%)",
          backgroundSize: "200% 100%",
          animation: "shimmer 1.5s infinite",
          animationDelay: "0.8s",
        }}
      />
    </div>
  );
}

interface PanelContentProps {
  mvsData: MVSData;
}

function PanelContent({ mvsData }: PanelContentProps) {
  const dims = mvsData.dimensions ?? [];

  return (
    <>
      {/* Gauge + State row */}
      <div style={{ textAlign: "center", marginBottom: 8 }}>
        <MVSGauge composite={mvsData.composite} />
        <div style={{ marginTop: 4 }}>
          <StateBadge state={mvsData.market_state} />
        </div>
      </div>

      {/* Dimensions section */}
      <div style={{ marginBottom: 12 }}>
        <SectionTitle text="Dimensions" />
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {dims.map((d) => (
            <DimensionBar
              key={d.name}
              name={d.name}
              score={d.score}
              weight={d.weight}
              is_stale={d.is_stale}
            />
          ))}
        </div>
      </div>

      {/* Market Impact section */}
      <div style={{ marginBottom: 12 }}>
        <SectionTitle text="Market Impact" />
        <ImpactSummary
          temperature_adjustment={mvsData.temperature_adjustment}
          directional_bias={mvsData.directional_bias}
          band_width_multiplier={mvsData.band_width_multiplier}
          signal_threshold={mvsData.signal_threshold}
          confidence_override={mvsData.confidence_override}
        />
      </div>

      {/* Footer */}
      <div
        style={{
          marginTop: "auto",
          paddingTop: 12,
          borderTop: "1px solid #2a2a3e",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "#6b7280",
        }}
      >
        <span>Updated {relativeTime(mvsData.created_at)}</span>
        <span>
          VIX:{" "}
          {mvsData.vix_value != null
            ? mvsData.vix_value.toFixed(2)
            : "N/A"}
        </span>
      </div>
    </>
  );
}

function SectionTitle({ text }: { text: string }) {
  return (
    <h3
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: "#9ca3af",
        textTransform: "uppercase",
        letterSpacing: "1px",
        marginBottom: 8,
      }}
    >
      {text}
    </h3>
  );
}

export default function MarketVariancePanel() {
  const { mvsData, connected, error } = useVarianceWS();

  const panelStyle: React.CSSProperties = useMemo(
    () => ({
      width: 320,
      minWidth: 320,
      height: "100vh",
      backgroundColor: "#1a1a2e",
      borderLeft: "1px solid #2a2a3e",
      display: "flex",
      flexDirection: "column",
      overflowY: "auto",
      padding: 16,
      boxSizing: "border-box",
    }),
    []
  );

  function renderBody() {
    // Error state
    if (error) {
      return (
        <div
          style={{
            padding: 16,
            color: "#dc2626",
            fontSize: 13,
            textAlign: "center",
          }}
        >
          {error}
        </div>
      );
    }

    // Not connected
    if (!connected) {
      return (
        <div
          style={{
            padding: 24,
            textAlign: "center",
            color: "#9ca3af",
            fontSize: 13,
          }}
        >
          <span>Connecting</span>
          <span className="connecting-dots" />
        </div>
      );
    }

    // Connected but no data yet — show skeleton
    if (!mvsData) {
      return <LoadingSkeleton />;
    }

    // Has data
    return <PanelContent mvsData={mvsData} />;
  }

  return (
    <aside style={panelStyle}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: "1px solid #2a2a3e",
        }}
      >
        <h2
          style={{
            fontSize: 14,
            fontWeight: 700,
            color: "#e0e0e0",
            margin: 0,
          }}
        >
          Market Variance
        </h2>
        <ConnectionDot connected={connected} />
      </div>

      {renderBody()}
    </aside>
  );
}
