import { useVarianceWS } from "./hooks/useVarianceWS";
import MarketVariancePanel from "./components/MarketVariancePanel";
import CandleChartOverlay from "./components/CandleChartOverlay";
import FearPanicBanner from "./components/FearPanicBanner";
import DQGMveRow from "./components/DQGMveRow";

function App() {
  const { mvsData } = useVarianceWS();

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Main chart area */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", background: "#0f0f1a" }}>
        {/* FEAR/PANIC banner — sticky top per D-08 */}
        <FearPanicBanner mvsData={mvsData} />

        {/* Chart container */}
        <div style={{ flex: 1, position: "relative" }}>
          <CandleChartOverlay mvsData={mvsData} />
        </div>

        {/* DQG MVE status row — bottom of chart area */}
        <div style={{ padding: "8px 12px", borderTop: "1px solid #1a1a2e" }}>
          <DQGMveRow />
        </div>
      </main>

      {/* Right sidebar — MarketVariancePanel per D-05 */}
      <MarketVariancePanel />
    </div>
  );
}

export default App;
