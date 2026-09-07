+++
title = "NASA-STD-5020A: preload uncertainty by installation method, locking rules, engagement"
kind = "reference_value"
audience = "reference"
applicability = []
derivation = "facts_extracted"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/nasa-rp-1228-torque-coefficient-and-why-torque-is-a-poor-proxy", "corpus:mechanical/fasteners/thread-engagement-length", "corpus:mechanical/fasteners/nasa-rp-1228-locking-methods-and-lockwashers"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "us_government_work"
source_title = "Requirements for Threaded Fastening Systems in Spaceflight Hardware, NASA-STD-5020A with Change 1 (approved for public release, distribution unlimited)"
source_publisher = "NASA"
source_url = "https://www.nasa.gov/wp-content/uploads/2018/01/nasa-std-5020a_w-chg_1_nasa_fastener_standards.pdf"
source_locator = "approved 2018-09-04; §4.3, Table (preload variation), §4.6 [TFSR 17–19], §4.7.4 [TFSR 23], Figure 2"
source_license = "public-domain-us-gov"
accessed_at = 2026-09-06
attribution = "NASA, NASA-STD-5020A, approved 2018-09-04; §4.3, Table (preload variation), §4.6 [TFSR 17–19], §4.7.4 [TFSR 23], Figure 2 (work of the US Government, public use permitted)"
+++

NASA-STD-5020A is the standard that turns the Fastener Design Manual's cautions into
requirements. It is written for spaceflight hardware; the facts below are the ones a robot team
can use directly, each with where it comes from.

Installation methods and their accuracy. §4.3 lists the common ways of setting preload in order
of increasing labour, cost, and accuracy: controlling installation torque, controlling the turn
angle after seating, measuring the fastener's stretch, and strain-gauging the bolt. Torque
control, the cheapest and the one every robot shop uses, is stated to be the least accurate.

The uncertainty the standard assigns. Absent a statistical basis from tests, the preload
variation to carry through the analysis when using torque control is the greater of 25 % for
fasteners lubricated at assembly and 35 % for non-lubricated or as-received fasteners (or the
variation found from tests). For turn-of-nut or turn-angle control the corresponding figure is
25 %. These are the numbers to put on a joint calculation when you set a bolt with a torque
wrench and have not measured your own scatter.

Locking. Every threaded fastening system must have a locking feature regardless of preload
([TFSR 16]); where a bolt rotates in service (is subject to rotation about its axis), a mechanical locking
feature is required, because the forces involved can overcome a friction-based lock, whether a
prevailing-torque nut or a threadlocker adhesive ([TFSR 17]); adhesive locking is subject to its own controls ([TFSR 18]); and
the presence and performance of the locking feature, its locking moment, must be verified
([TFSR 19]), by measuring prevailing torque unless a documented alternative is in place.

Thread engagement. With a prevailing-torque feature the fastener must be long enough for fully
formed threads to engage it ([TFSR 23]). The standard's guidance figure: with a nut, nut plate, or
insert, the fastener should extend at least two thread pitches past the outboard face so that
incomplete lead and runout threads are clear of the engagement. For a tapped part that is not a
nut or insert, choose the engaged length so the fastener fails in tension before the threads
strip; a tensile failure is easier to detect and repair and redistributes load more gracefully.

Applicability: the percentages are the standard's defaults for analysis without test data. A team
that measures its own torque–preload scatter may use its measured value instead; a team that
does not should not assume better than these.
