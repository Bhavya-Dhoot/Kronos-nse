import MarketVariancePanel from "./components/MarketVariancePanel";

function App() {
  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Main chart area — placeholder for CandleChart (Plan 08-04) */}
      <main style={{ flex: 1, background: "#0f0f1a" }}>
        <h1 style={{ color: "#666", padding: 24 }}>Chart Area</h1>
      </main>
      {/* Right sidebar — MarketVariancePanel per D-05 */}
      <MarketVariancePanel />
    </div>
  );
}

export default App;
