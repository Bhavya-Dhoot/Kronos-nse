import { useMemo } from "react";

interface MVSGaugeProps {
  composite: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/** Map composite [-1, 1] to an angle in degrees [0, 180] where:
 *  -1.0 → 180° (far left)
 *   0.0 →  90° (straight down)
 *  +1.0 →   0° (far right)
 */
function compositeToAngle(composite: number): number {
  return 90 - clamp(composite, -1, 1) * 90;
}

function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number
): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function describeArc(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number
): string {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0;
  return [
    "M",
    start.x,
    start.y,
    "A",
    r,
    r,
    0,
    largeArcFlag,
    0,
    end.x,
    end.y,
  ].join(" ");
}

export default function MVSGauge({ composite }: MVSGaugeProps) {
  const cx = 100;
  const cy = 100;
  const r = 80;
  const needleLen = 68;

  const angle = compositeToAngle(composite);
  const needleTip = useMemo(
    () => polarToCartesian(cx, cy, needleLen, angle),
    [angle]
  );

  // Colored arc from composite=-1.0 (180°) to current value
  const coloredArcPath = useMemo(
    () => describeArc(cx, cy, r, angle, 180),
    [angle]
  );

  // Background arc (full semi-circle)
  const bgArcPath = useMemo(
    () => describeArc(cx, cy, r, 0, 180),
    []
  );

  const displayValue =
    composite > 0
      ? `+${composite.toFixed(2)}`
      : composite.toFixed(2);

  return (
    <svg
      viewBox="0 0 200 130"
      style={{ width: "100%", maxWidth: 200, display: "block" }}
      role="img"
      aria-label={`MVS composite score: ${displayValue}`}
    >
      <defs>
        <linearGradient id="mvs-arc-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#dc2626" />    {/* Red */}
          <stop offset="50%" stopColor="#d97706" />   {/* Amber */}
          <stop offset="100%" stopColor="#16a34a" />   {/* Green */}
        </linearGradient>
      </defs>

      {/* Background track */}
      <path
        d={bgArcPath}
        fill="none"
        stroke="#2a2a3e"
        strokeWidth={12}
        strokeLinecap="round"
      />

      {/* Colored arc */}
      <path
        d={coloredArcPath}
        fill="none"
        stroke="url(#mvs-arc-gradient)"
        strokeWidth={12}
        strokeLinecap="round"
        style={{ transition: "d 0.4s ease" }}
      />

      {/* Needle */}
      <line
        x1={cx}
        y1={cy}
        x2={needleTip.x}
        y2={needleTip.y}
        stroke="#e0e0e0"
        strokeWidth={2.5}
        strokeLinecap="round"
        style={{ transition: "all 0.4s ease" }}
      />

      {/* Center dot */}
      <circle cx={cx} cy={cy} r={4} fill="#e0e0e0" />

      {/* Composite value text */}
      <text
        x={cx}
        y={cy + 28}
        textAnchor="middle"
        fill="#e0e0e0"
        fontSize={18}
        fontFamily="ui-monospace, monospace"
        fontWeight={600}
      >
        {displayValue}
      </text>
    </svg>
  );
}
