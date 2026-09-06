+++
title = "Threaded inserts: why aerospace puts a steel thread in soft metal and plastic"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "summary"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/heat-set-inserts-in-printed-parts", "corpus:mechanical/fasteners/thread-engagement-length"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "us_government_work"
source_title = "Fastener Design Manual, NASA Reference Publication 1228 (Richard T. Barrett, Lewis Research Center)"
source_publisher = "NASA"
source_url = "https://ntrs.nasa.gov/citations/19900009424"
source_locator = "March 1990, Inserts chapter, pp. 12–14, Figures 17–18"
source_license = "public-domain-us-gov"
accessed_at = 2026-09-06
attribution = "NASA, NASA RP-1228, March 1990, Inserts chapter, pp. 12–14, Figures 17–18 (work of the US Government, public use permitted)"
+++

The Fastener Design Manual explains inserts from the aerospace point of view, which is exactly
the robot-builder's problem: a strong, reusable thread in a material that cannot hold one.

What an insert is. A device threaded on its inside and anchored on its outside (by its own
external thread, or by knurls, serrations, grooves, or an interference fit) in a drilled, moulded,
or tapped hole. Its purpose is a wear-resistant tapped hole in soft materials such as plastics
and non-ferrous metals, and the repair of a stripped thread.

Why aerospace uses them. A small high-strength bolt saves weight, but its thread would tear out
of aluminium or plastic. The insert's larger external thread spreads the load: the manual's
example is a 10-32 screw effectively engaging the parent material through an insert whose outside
is a 5/16-18 thread, since the external thread is nominally 1/8 in larger in diameter than the
internal one.

The three threaded types the manual distinguishes. The wire-thread insert (the Heli-Coil
family) is a precision coil of diamond-section stainless wire forming both threads, made slightly
oversize for an interference fit in the tapped hole, with a tang broken off after installation;
it is the most popular repair insert because it needs the least hole enlargement, and a version
with a deformed coil adds locking. Self-tapping inserts are mostly solid bushings with a tapered
external thread that cut their own way in. Solid bushing inserts are the manual's preference
where space permits, because the bushing is stronger and simpler than a coil.

How this maps to robot parts. In machined aluminium arms and brackets a wire-thread or
solid-bushing insert turns a thread that would strip after a few cycles into one that survives
service. In printed plastics the same principle appears as heat-set or moulded-in inserts, which
the manual predates; the design logic is unchanged, and the engagement-length reasoning is
identical: the failure you want is the bolt in tension, not the insert pulling out of the parent.
