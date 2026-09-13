export default function SolusMark({ size = 26 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" aria-hidden="true">
      <polygon points="90,26 38,44 82,76 30,94" fill="#0b0e13" />
      <path
        d="M90 26 L38 44 L82 76 L30 94"
        stroke="#2f6bdc"
        strokeWidth="5"
        strokeLinecap="round"
        fill="none"
      />
      <circle
        cx="90"
        cy="26"
        r="10"
        fill="#0b0e13"
        stroke="#4c8dff"
        strokeWidth="5"
      />
      <circle
        cx="30"
        cy="94"
        r="10"
        fill="#0b0e13"
        stroke="#4c8dff"
        strokeWidth="5"
      />
      <circle cx="38" cy="44" r="14" fill="#7fadff" />
      <circle cx="82" cy="76" r="14" fill="#7fadff" />
    </svg>
  );
}
