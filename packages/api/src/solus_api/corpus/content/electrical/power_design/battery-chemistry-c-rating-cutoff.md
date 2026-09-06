+++
title = "Battery cell voltages, C-rating, and low-voltage cutoff for common robot chemistries"
kind = "reference_value"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/power_design/ldo-vs-buck-vs-boost"]
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "bq297xx single-cell lithium-ion battery protection IC datasheet family", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
  { title = "LTC4054 standalone linear lithium-ion battery charger datasheet", author = "Analog Devices", identifier = "", url = "https://www.analog.com/" },
]
+++

Per-cell values for the chemistries that appear in robots. Pack voltage is the cell value times the series count (S); a "4S LiPo" is four cells in series.

| Chemistry | Nominal | Full charge | Do not discharge below | Notes |
| --- | --- | --- | --- | --- |
| Li-ion / LiPo (cobalt or NMC cathode) | 3.6–3.7 V | 4.2 V | about 3.0 V | protection ICs trip roughly 2.5–3.0 V; 4.2 V is the standard charge limit, not a margin |
| LiFePO4 | 3.2 V | 3.6–3.65 V | about 2.5 V | flat discharge curve, so voltage is a poor fuel gauge |
| NiMH | 1.2 V | about 1.4–1.5 V on charge | about 1.0 V | tolerant, heavy, self-discharges |

Conditions: these are the widely published figures for standard cells at room temperature; a specific cell's datasheet governs, and cold cells sag well below these numbers under load.

C-rating expresses current as a multiple of capacity. On a 5 Ah pack, 1 C is 5 A and 20 C is 100 A. Cells carry separate continuous and burst (a few seconds) ratings; the burst figure is the one printed largest on hobby packs. Design the harness, connectors, and fusing to the continuous rating you actually draw, and treat advertised hobby-pack C ratings as optimistic unless the datasheet shows a discharge curve at that rate.

A battery management system (BMS) or protection circuit provides over-charge, over-discharge, over-current, short-circuit, and temperature protection, and on multi-cell packs balances the cells. It is a safety device that trips at the edge of the cell's survival range, not a fuel gauge: firmware should implement its own low-voltage cutoff above the protector's threshold (for Li-ion, stopping the mission around 3.3–3.5 V per cell under light load is a common choice) and warn earlier still. Discharging a lithium cell below its cutoff damages it permanently, and recharging a deeply discharged cell is a fire risk that chargers refuse for good reason.
