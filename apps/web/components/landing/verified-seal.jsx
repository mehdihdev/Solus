const SEAL_POINTS =
  "10,0.5 11.86,3.05 14.75,1.77 15.09,4.91 18.23,5.25 16.95,8.14 19.5,10 " +
  "16.95,11.86 18.23,14.75 15.09,15.09 14.75,18.23 11.86,16.95 10,19.5 " +
  "8.14,16.95 5.25,18.23 4.91,15.09 1.77,14.75 3.05,11.86 0.5,10 3.05,8.14 " +
  "1.77,5.25 4.91,4.91 5.25,1.77 8.14,3.05";

export default function VerifiedSeal({ size = 13, style }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      style={style}
      aria-hidden="true"
    >
      <polygon points={SEAL_POINTS} fill="#3ddc97" />
      <path
        d="M6.4 10.3 L9 12.8 L13.8 7.5"
        fill="none"
        stroke="#0b0e13"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
