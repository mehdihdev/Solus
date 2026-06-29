// Makes @testing-library/jest-dom matchers (toBeInTheDocument, toHaveAttribute,
// toBeDisabled, …) visible to tsc. The runtime registration lives in
// test/setup.ts; this brings in the matching type augmentation for Vitest.
import '@testing-library/jest-dom/vitest'
