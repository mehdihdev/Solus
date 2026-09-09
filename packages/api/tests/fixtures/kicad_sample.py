"""Sample committed KiCad exports (SOLUSDEV-100 W0-08 §5.2; SOLUSDEV-252 §5.2a).

One design — an op-amp, a resistor, a decoupling cap across VCC / GND / a signal
net — rendered in every shape the KiCad connector ingests, so the parsers can be
held to parity against each other:

* `KICAD_XML` — the KiCad 8 XML netlist (`--format kicadxml`). U1 carries its
  MPN as a v5-style `<field>`; R1 as a v6+ `<property>` under an alias; C1 has
  the "~" placeholder datasheet (absence, not content). U1 also carries a
  v5-vs-v6 name collision ("Grade") — the later `<property>` must win.
* `KICAD_SEXPR` — the SAME netlist in KiCad's default S-expression `.net` form.
* `KICAD_PCB` — a KiCad-9-format board of the same design, plus board-only
  parts (a mounting hole, a fiducial in KiCad-7 `fp_text` style, a
  reference-less logo footprint), an unconnected-net header and copper noise
  (segments/vias/zones/graphics) the board parser must prune.
* `KICAD_SCHEMATIC_HEAD` / `KICAD_PROJECT_HEAD` — the opening of a raw
  `.kicad_sch` / `.kicad_pro`; both are refused, never half-parsed.
"""

KICAD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <design>
    <source>/work/robot/power.kicad_sch</source>
    <date>2026-06-30</date>
    <tool>Eeschema 8.0.4</tool>
  </design>
  <components>
    <comp ref="U1">
      <value>LM358</value>
      <footprint>Package_SO:SOIC-8_3.9x4.9mm_P1.27mm</footprint>
      <datasheet>https://www.ti.com/lit/ds/symlink/lm358.pdf</datasheet>
      <fields>
        <field name="MPN">LM358DR</field>
        <field name="Tolerance">n/a</field>
        <field name="Grade">commercial</field>
      </fields>
      <libsource lib="Amplifier_Operational" part="LM358" description="Dual op-amp"/>
      <property name="Grade" value="industrial"/>
      <sheetpath names="/" tstamps="/"/>
      <tstamps>00000000-0000-0000-0000-000000000001</tstamps>
    </comp>
    <comp ref="R1">
      <value>10k</value>
      <footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <property name="Manufacturer_Part_Number" value="RC0603FR-0710KL"/>
      <libsource lib="Device" part="R"/>
    </comp>
    <comp ref="C1">
      <value>100nF</value>
      <footprint>Capacitor_SMD:C_0603_1608Metric</footprint>
      <datasheet>~</datasheet>
      <libsource lib="Device" part="C"/>
    </comp>
  </components>
  <nets>
    <net code="1" name="VCC" class="Power">
      <node ref="U1" pin="8" pinfunction="V+" pintype="power_in"/>
      <node ref="C1" pin="1" pintype="passive"/>
    </net>
    <net code="2" name="GND">
      <node ref="U1" pin="4" pinfunction="V-" pintype="power_in"/>
      <node ref="C1" pin="2" pintype="passive"/>
    </net>
    <net code="3" name="SIGNAL">
      <node ref="U1" pin="1" pintype="output"/>
      <node ref="R1" pin="2" pintype="passive"/>
    </net>
  </nets>
</export>
"""

KICAD_SEXPR = """(export
  (version "E")
  (design
    (source "/work/robot/power.kicad_sch")
    (date "2026-06-30")
    (tool "Eeschema 8.0.4"))
  (components
    (comp
      (ref "U1")
      (value "LM358")
      (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
      (datasheet "https://www.ti.com/lit/ds/symlink/lm358.pdf")
      (description "Dual op-amp")
      (fields
        (field (name "MPN") "LM358DR")
        (field (name "Tolerance") "n/a")
        (field (name "Grade") "commercial"))
      (libsource (lib "Amplifier_Operational") (part "LM358") (description "Dual op-amp"))
      (property (name "Grade") (value "industrial"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "00000000-0000-0000-0000-000000000001"))
    (comp
      (ref "R1")
      (value "10k")
      (footprint "Resistor_SMD:R_0603_1608Metric")
      (property (name "Manufacturer_Part_Number") (value "RC0603FR-0710KL"))
      (libsource (lib "Device") (part "R")))
    (comp
      (ref "C1")
      (value "100nF")
      (footprint "Capacitor_SMD:C_0603_1608Metric")
      (datasheet "~")
      (libsource (lib "Device") (part "C"))))
  (libparts
    (libpart (lib "Device") (part "C") (description "Unpolarized capacitor")))
  (libraries
    (library (logical "Device") (uri "/usr/share/kicad/symbols/Device.kicad_sym")))
  (nets
    (net (code "1") (name "VCC") (class "Power")
      (node (ref "U1") (pin "8") (pinfunction "V+") (pintype "power_in"))
      (node (ref "C1") (pin "1") (pintype "passive")))
    (net (code "2") (name "GND")
      (node (ref "U1") (pin "4") (pinfunction "V-") (pintype "power_in"))
      (node (ref "C1") (pin "2") (pintype "passive")))
    (net (code "3") (name "SIGNAL")
      (node (ref "U1") (pin "1") (pintype "output"))
      (node (ref "R1") (pin "2") (pintype "passive")))))
"""

KICAD_PCB = """(kicad_pcb
  (version 20241229)
  (generator "pcbnew")
  (generator_version "9.0")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (2 "B.Cu" signal)
    (25 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no))
  (net 0 "")
  (net 1 "VCC")
  (net 2 "GND")
  (net 3 "SIGNAL")
  (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    (layer "F.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000001")
    (at 100 50)
    (descr "SOIC, 8 Pin (JEDEC MS-012AA)")
    (tags "SOIC SO")
    (property "Reference" "U1"
      (at 0 -3.4 0) (layer "F.SilkS") (uuid "0b2a6d3e-0000-4000-8000-000000000101")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "LM358"
      (at 0 3.4 0) (layer "F.Fab") (uuid "0b2a6d3e-0000-4000-8000-000000000102")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Footprint" "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000103")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Datasheet" "https://www.ti.com/lit/ds/symlink/lm358.pdf"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000104")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Description" "Dual op-amp"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000105")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "MPN" "LM358DR"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000106")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Tolerance" "n/a"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000107")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Grade" "industrial"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000108")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "ki_keywords" "dual opamp"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000109")
      (effects (font (size 1 1) (thickness 0.15))))
    (path "/00000000-0000-0000-0000-000000000001")
    (sheetname "/")
    (sheetfile "power.kicad_sch")
    (attr smd)
    (fp_line (start -1.95 -2.45) (end 1.95 -2.45)
      (stroke (width 0.12) (type solid)) (layer "F.SilkS")
      (uuid "0b2a6d3e-0000-4000-8000-000000000110"))
    (fp_text user "${REFERENCE}"
      (at 0 0 0) (layer "F.Fab") (uuid "0b2a6d3e-0000-4000-8000-000000000111")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect
      (at -2.7 -1.905) (size 1.55 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (net 3 "SIGNAL") (pinfunction "OUT1") (pintype "output")
      (uuid "0b2a6d3e-0000-4000-8000-000000000121"))
    (pad "2" smd roundrect
      (at -2.7 -0.635) (size 1.55 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (pinfunction "-IN1") (pintype "input")
      (uuid "0b2a6d3e-0000-4000-8000-000000000122"))
    (pad "4" smd roundrect
      (at -2.7 1.905) (size 1.55 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (net 2 "GND") (pinfunction "V-") (pintype "power_in")
      (uuid "0b2a6d3e-0000-4000-8000-000000000124"))
    (pad "8" smd roundrect
      (at 2.7 -1.905) (size 1.55 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (net 1 "VCC") (pinfunction "V+") (pintype "power_in")
      (uuid "0b2a6d3e-0000-4000-8000-000000000128"))
    (model "${KICAD9_3DMODEL_DIR}/Package_SO.3dshapes/SOIC-8_3.9x4.9mm_P1.27mm.wrl"
      (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0))))
  (footprint "Resistor_SMD:R_0603_1608Metric"
    (layer "F.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000002")
    (at 110 50)
    (property "Reference" "R1"
      (at 0 -1.43 0) (layer "F.SilkS") (uuid "0b2a6d3e-0000-4000-8000-000000000201")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "10k"
      (at 0 1.43 0) (layer "F.Fab") (uuid "0b2a6d3e-0000-4000-8000-000000000202")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000203")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Datasheet" "~"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000204")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Description" "Resistor"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000205")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Manufacturer_Part_Number" "RC0603FR-0710KL"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000206")
      (effects (font (size 1 1) (thickness 0.15))))
    (attr smd)
    (pad "1" smd roundrect
      (at -0.7875 0) (size 0.875 0.95) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (uuid "0b2a6d3e-0000-4000-8000-000000000221"))
    (pad "2" smd roundrect
      (at 0.7875 0) (size 0.875 0.95) (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25) (net 3 "SIGNAL") (pintype "passive")
      (uuid "0b2a6d3e-0000-4000-8000-000000000222")))
  (footprint "Capacitor_SMD:C_0603_1608Metric"
    (layer "B.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000003")
    (at 100 60)
    (property "Reference" "C1"
      (at 0 -1.43 0) (layer "B.SilkS") (uuid "0b2a6d3e-0000-4000-8000-000000000301")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "100nF"
      (at 0 1.43 0) (layer "B.Fab") (uuid "0b2a6d3e-0000-4000-8000-000000000302")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Footprint" "Capacitor_SMD:C_0603_1608Metric"
      (at 0 0 0) (layer "B.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000303")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Datasheet" "~"
      (at 0 0 0) (layer "B.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000304")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Description" "Unpolarized capacitor"
      (at 0 0 0) (layer "B.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000305")
      (effects (font (size 1 1) (thickness 0.15))))
    (attr smd)
    (pad "1" smd roundrect
      (at -0.775 0) (size 0.9 0.95) (layers "B.Cu" "B.Paste" "B.Mask")
      (roundrect_rratio 0.25) (net 1 "VCC") (pintype "passive")
      (uuid "0b2a6d3e-0000-4000-8000-000000000321"))
    (pad "2" smd roundrect
      (at 0.775 0) (size 0.9 0.95) (layers "B.Cu" "B.Paste" "B.Mask")
      (roundrect_rratio 0.25) (net 2 "GND") (pintype "passive")
      (uuid "0b2a6d3e-0000-4000-8000-000000000322")))
  (footprint "MountingHole:MountingHole_3.2mm_M3"
    (layer "F.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000004")
    (at 90 40)
    (property "Reference" "H1"
      (at 0 -3.2 0) (layer "F.SilkS") (uuid "0b2a6d3e-0000-4000-8000-000000000401")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "MountingHole_3.2mm_M3"
      (at 0 3.2 0) (layer "F.Fab") (uuid "0b2a6d3e-0000-4000-8000-000000000402")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Footprint" "MountingHole:MountingHole_3.2mm_M3"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000403")
      (effects (font (size 1 1) (thickness 0.15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (pad "" np_thru_hole circle
      (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask")
      (uuid "0b2a6d3e-0000-4000-8000-000000000421")))
  (footprint "Fiducial:Fiducial_1mm_Mask2mm"
    (layer "F.Cu")
    (tedit 5E7D6D7B)
    (tstamp 0b2a6d3e-0000-4000-8000-000000000005)
    (at 130 70)
    (attr exclude_from_pos_files exclude_from_bom)
    (fp_text reference "FID1" (at 0 -2) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value "Fiducial" (at 0 2) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "" smd circle (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask")))
  (footprint "Symbol:OSHW-Logo_6.7x6mm_SilkScreen"
    (layer "F.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000006")
    (at 120 65)
    (property "Value" "LOGO"
      (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "0b2a6d3e-0000-4000-8000-000000000602")
      (effects (font (size 1 1) (thickness 0.15))))
    (attr board_only exclude_from_pos_files exclude_from_bom)
    (fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (stroke (width 0) (type solid))
      (fill solid) (layer "F.SilkS") (uuid "0b2a6d3e-0000-4000-8000-000000000610")))
  (segment (start 100 50) (end 110 50) (width 0.25) (layer "F.Cu") (net 1)
    (uuid "0b2a6d3e-0000-4000-8000-000000000701"))
  (segment (start 110 50) (end 110 60) (width 0.25) (layer "F.Cu") (net 3)
    (uuid "0b2a6d3e-0000-4000-8000-000000000702"))
  (via (at 105 50) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 2)
    (uuid "0b2a6d3e-0000-4000-8000-000000000703"))
  (zone (net 2) (net_name "GND") (layer "B.Cu")
    (uuid "0b2a6d3e-0000-4000-8000-000000000704")
    (hatch edge 0.5) (connect_pads (clearance 0.5)) (min_thickness 0.25)
    (filled_areas_thickness no)
    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))
    (polygon (pts (xy 90 40) (xy 130 40) (xy 130 70) (xy 90 70)))
    (filled_polygon (layer "B.Cu") (pts (xy 90.5 40.5) (xy 129.5 40.5) (xy 129.5 69.5))))
  (gr_line (start 90 40) (end 130 40) (stroke (width 0.05) (type default))
    (layer "Edge.Cuts") (uuid "0b2a6d3e-0000-4000-8000-000000000705"))
  (embedded_fonts no)
)
"""

KICAD_SCHEMATIC_HEAD = """(kicad_sch
  (version 20250114)
  (generator "eeschema")
  (generator_version "9.0")
  (uuid "38ba17ef-e180-5855-b4a7-5d12652abdb5")
  (paper "A4")
  (lib_symbols)
  (symbol (lib_id "Device:R") (at 100 50 0) (unit 1)
    (property "Reference" "R1" (at 102 49 0))
    (property "Value" "10k" (at 102 51 0)))
)
"""

KICAD_PROJECT_HEAD = """{
  "board": {
    "design_settings": {
      "defaults": {}
    }
  },
  "meta": {
    "filename": "power.kicad_pro",
    "version": 3
  },
  "schematic": {}
}
"""
