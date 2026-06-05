import { useEffect, useRef } from "react";
import { createChart, ColorType, IChartApi } from "lightweight-charts";
import type { MVSData } from "../types/variance";

interface CandleChartOverlayProps {
  mvsData: MVSData | null;
}

function compositeToRgba(composite: number, opacity: number): string {
  const normalized = (composite + 1.0) / 2; // 0.0 to 1.0
  const red = Math.round((1 - normalized) * 50);
  const green = Math.round(normalized * 50);
  const blue = 20;
  return `rgba(${red + 20}, ${green + 20}, ${blue}, ${opacity})`;
}

export default function CandleChartOverlay({ mvsData }: CandleChartOverlayProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0f0f1a" },
        textColor: "#888",
      },
      grid: {
        vertLines: { color: "#1a1a2e" },
        horzLines: { color: "#1a1a2e" },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      crosshair: { mode: 0 },
    });

    chartRef.current = chart;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Apply MVS background tint per D-07
  useEffect(() => {
    if (!chartRef.current || !mvsData) return;
    const composite = mvsData.composite;
    const topColor = compositeToRgba(composite, 0.15);
    const bottomColor = compositeToRgba(composite, 0.05);

    chartRef.current.applyOptions({
      layout: {
        background: {
          type: ColorType.VerticalGradient,
          topColor,
          bottomColor,
        },
      },
    });
  }, [mvsData]);

  const isFearPanic = mvsData?.market_state === "panic" || mvsData?.market_state === "fear";

  return (
    <div
      ref={chartContainerRef}
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        border: isFearPanic ? "2px solid #dc2626" : "2px solid transparent",
        borderRadius: 4,
        transition: "border-color 0.3s ease",
      }}
    />
  );
}
