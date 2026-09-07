+++
title = "Category, performance level, and safe torque off: the vocabulary, not a checklist"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/safety_interlocks/estop-is-a-hardware-chain", "corpus:systems/safety_interlocks/interlock-vs-enable-pitfalls"]
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
  { title = "ISO 13849-1 Safety of machinery — Safety-related parts of control systems — Part 1: General principles for design", author = "ISO", identifier = "ISO 13849-1", url = "https://www.iso.org/" },
  { title = "IEC 61800-5-2 Adjustable speed electrical power drive systems — Part 5-2: Safety requirements — Functional", author = "IEC", identifier = "IEC 61800-5-2", url = "https://www.iec.ch/" },
  { title = "IEC 62061 Safety of machinery — Functional safety of safety-related control systems", author = "IEC", identifier = "IEC 62061", url = "https://www.iec.ch/" },
]
+++

This is what these words mean when a drive datasheet or a safety engineer uses them.

A safety function is a specific behaviour with a specific trigger: stop the arm when the door opens; prevent motion above a speed while a person is inside the cell. The hardware and software that carry out one safety function are the safety-related parts of the control system, and ISO 13849-1 is the standard about how to design those parts. It gives two vocabulary axes.

Performance level (PL) is a graded statement, from level a to level e, of how reliably a safety function can be expected to do its job. It is not a component property; it emerges from the structure of the channel, the reliability of the parts in it, how well faults in it are detected, and how likely a single cause is to fail both channels at once. The PL a machine requires is an output of a risk assessment of that machine; it is never assumed and never inherited from a component's label.

Category is the structural vocabulary: it describes the architecture of the channel, from a single channel built with basic principles, through a single channel with testing, to redundant channels with monitoring. Two designs in the same category can reach different PLs, and category alone says nothing about a machine being safe. IEC 62061 is the sibling standard on the electrical and programmable side.

Safe torque off (STO) is one named drive safety function from IEC 61800-5-2. It removes the drive's ability to produce torque, typically by disabling the gate drive to the power stage, while leaving the drive's logic powered so it can report state and recover quickly. Three consequences matter for robots. STO is not a brake: a motor under STO coasts, and a gravity-loaded joint falls, so an arm needs a mechanical brake that engages when de-energised in addition to STO. STO removes torque but not necessarily the bus voltage, so it is not electrical isolation for maintenance. And a drive's STO input is a dual-channel hardware input for exactly the reason the emergency-stop chain is hardware: a stop that arrives over the same fieldbus as the motion commands is a command, not a safety function. The same standard names safe stop 1 (a controlled deceleration followed by STO) and other functions a drive datasheet may list.

Solus can explain what these terms mean and point at the standards that define them. Assigning a category or PL, or stating that a design complies, is a task for a qualified functional-safety assessment.
