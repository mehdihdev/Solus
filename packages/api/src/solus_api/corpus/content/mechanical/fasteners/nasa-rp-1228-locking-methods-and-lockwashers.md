+++
title = "Locking methods that work, and the lockwasher that does not"
kind = "pitfall"
audience = "reference"
applicability = [{ key = "environment", value = "vibration" }]
derivation = "summary"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/locking-methods", "corpus:mechanical/fasteners/nasa-rp-1228-torque-coefficient-and-why-torque-is-a-poor-proxy"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "us_government_work"
source_title = "Fastener Design Manual, NASA Reference Publication 1228 (Richard T. Barrett, Lewis Research Center)"
source_publisher = "NASA"
source_url = "https://ntrs.nasa.gov/citations/19900009424"
source_locator = "March 1990, Locking Methods and Washers chapters, pp. 6–12"
source_license = "public-domain-us-gov"
accessed_at = 2026-09-06
attribution = "NASA, NASA RP-1228, March 1990, Locking Methods and Washers chapters, pp. 6–12 (work of the US Government, public use permitted)"
+++

The Fastener Design Manual's chapters on locking methods and washers are blunt about which
devices lock and which merely look like they do. In Solus's words:

Where the locking lives. In a tapped hole the locking element is normally on the bolt (a
prevailing-torque patch or a deformed thread), because the hole cannot supply it. With a nut,
the nut carries it. Locking devices come in three families the manual describes: friction
(prevailing-torque nuts with deformed threads or a nylon collar, thread-locking adhesives),
mechanical (cotter pins, lockwire, tab washers, castellated nuts), and chemical (adhesives graded
by how often the joint must come apart).

Limits the manual records for the friction family: a nylon locking collar (the nylon-insert
locknut) has a temperature ceiling around 250 °F (about 120 °C) and a deformed-thread nut loses locking capability after
repeated reuse and must be discarded; a locking pellet pressed into a bolt can be a stress
concentration. Locking adhesives are made in several grades precisely so the strength can be
matched to the disassembly frequency.

The pitfall. The ordinary helical spring lockwasher (the split ring) acts as a spring only while
the bolt is being tightened; by the time the joint is preloaded it is flat, behaves as a flat
washer, and its locking ability is, in the manual's summary, nonexistent. Tooth (star)
lockwashers do provide some locking by biting into the mating surface, at the cost of damaging
that surface. Belleville washers are conical springs used mainly to maintain preload; they lock
only if not flattened, and plain ones without serrations add no significant locking.

What this means on a robot: a split lockwasher under a servo-horn screw or a motor-mount bolt is
decoration. Against vibration, use a prevailing-torque nut or a thread-locking compound at a
grade you can undo, keep the joint preloaded by design, and where a fastener rotates in service
(the joint is subject to rotation about the bolt axis) use a mechanical lock, which is the rule
NASA-STD-5020A makes explicit.
