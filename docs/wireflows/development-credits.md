# Development credit display

Authority: ADR-024 development exception; existing Billing screen and usage meter.
Keep existing navigation and card layout. For `unlimited=true`, show
“Unlimited (development)” in place of the finite credit allowance and suppress
credit exhaustion styling. Preserve the measured usage and real ledger balance
in API data. False or absent flags use the existing finite display.
