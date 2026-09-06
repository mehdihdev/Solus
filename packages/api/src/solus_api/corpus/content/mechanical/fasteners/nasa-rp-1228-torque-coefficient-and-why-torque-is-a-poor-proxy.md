+++
title = "T = K·F·d: the torque coefficient, its spread, and why torque only estimates preload"
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
related = ["corpus:mechanical/fasteners/preload-not-torque", "corpus:mechanical/fasteners/nasa-std-5020a-preload-variation-by-installation-method"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "us_government_work"
source_title = "Fastener Design Manual, NASA Reference Publication 1228 (Richard T. Barrett, Lewis Research Center)"
source_publisher = "NASA"
source_url = "https://ntrs.nasa.gov/citations/19900009424"
source_locator = "March 1990 (errata June 2008), Fastener Torque chapter, pp. 15–16, Tables IV–VI"
source_license = "public-domain-us-gov"
accessed_at = 2026-09-06
attribution = "NASA, NASA RP-1228, March 1990 (errata June 2008), Fastener Torque chapter, pp. 15–16, Tables IV–VI (work of the US Government, public use permitted)"
+++

NASA's Fastener Design Manual gives the compact form of the torque–preload relation and, more
usefully, the reasons it is unreliable. Facts extracted, with the manual's own framing:

The quick formula is T = K·F·d, where T is the installation torque, F the axial preload, d the
nominal bolt diameter, and K the torque coefficient (nut factor). K folds together the thread
friction, the underhead friction, the thread geometry, and the mean thread diameter; the manual
gives the full expression and tabulates K against friction coefficients.

The commonly assumed value is K = 0.2, and the manual says plainly that it should not be used
blindly: a more realistic typical value for steel on steel is about 0.15. The two friction
coefficients (threads, and bolt head or nut against the clamped surface) need not be equal, and
across materials and lubricants the coefficient of friction ranges from about 0.04 to 1.10, which
is why a torque table computed for one friction condition is wrong for another. Any running
torque from a locking feature is part of what the wrench sees and should be included in the
table value, since torque of any kind loads the bolt in shear.

Two guardrails from the same chapter. Fastener proof load, where quoted, is usually about 75 %
of theoretical yield, chosen so that torque-measurement error does not take the bolt into
yield. Torquing near yield to gain vibration resistance is sometimes done for bolts that cannot
otherwise be locked, but the manual advises against it: the exact yield torque cannot be known
without instrumentation, and a bolt that yields unloads.

Accuracy costs money. The manual lists torque-measuring methods from a mechanic's feel to strain
gauges on the bolt, and reproduces two experts' cost-versus-accuracy tables that disagree on the
numbers but agree on the trend: the cheaper the method, the wider the preload scatter. That
scatter is the reason a separately published NASA standard now assigns a preload uncertainty to
each installation method (see the related NASA-STD-5020A chunk).

Applicability: the relation and the caution hold for any threaded joint; the K values are for
the steel-on-steel and lubricated cases the manual tabulates, not for plastics or printed parts.
