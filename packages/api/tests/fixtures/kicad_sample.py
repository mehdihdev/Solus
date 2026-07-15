"""Sample committed KiCad 8 XML netlist (SOLUSDEV-100, W0-08 §5.2).

An op-amp, a resistor, a decoupling cap across VCC / GND / a signal net — the
electrical shape the whole EDA family maps. U1 carries its MPN as a v5-style
`<field>`; R1 as a v6+ `<property>` under an alias; C1 has the "~" placeholder
datasheet (absence, not content).
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
      </fields>
      <libsource lib="Amplifier_Operational" part="LM358" description="Dual op-amp"/>
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
