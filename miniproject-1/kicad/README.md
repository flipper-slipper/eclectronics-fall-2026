# MP1 LED Flasher — KiCad project

Open **MP1.kicad_pro** in KiCad 10. The schematic and completed board share this name. Keep the two library tables, MP1_Analog.kicad_sym, and MP1_Footprints.pretty alongside them.

## Minimal schematic

The schematic is one integrated drawing with a shared 3.3 V supply rail and the triangular op-amp symbol. Component values, pin connections, footprints and PCB associations are unchanged. Timing calculations and assembly details remain in MP1-Notes.md. The page retains your name and title block.

KiCad ERC: **0 errors and 0 warnings**. All 10 nets and 15 component associations match the completed PCB. See checks/minimal-layout-verification.json for the schematic simplification, and PCB-verification.json for the current board.

## Completed PCB

- Plain 18 × 22 mm rectangular outline (396 mm²), square corners, and 1.6 mm board thickness.
- Decorative titles, dates, size labels and nonessential board text removed. Component references, footprint outlines and polarity marks retained; no bottom-side printed text. References are aligned beside their components, with clearance from pads and outlines.
- Two copper layers. All 15 component bodies mount on top. All power and signal traces are routed on the top layer. The bottom ground plane has no routed tracks; the USB through-hole pads still appear on both copper layers.
- 0.25 mm signal tracks with a short 0.18 mm output escape beneath U1, and 0.4 mm main power routes; 0.20 mm minimum copper clearance; 0.30 mm copper-to-edge clearance.
- 9 ground through vias: 0.70 mm copper diameter and 0.35 mm drill. No via drills intersect component pads; minimum checked separation from a pad bounding box is 0.10 mm.
- C5 power pad is 1.788 mm from U1 pin 5, joined by a short direct trace. The high-impedance timing components sit beside U1.
- The USB plug projects beyond the bottom edge. The LED sits at the opposite end.

## Checks

KiCad 10.0.6 GUI DRC, with ground copper refilled: **0 errors, 0 warnings, 0 unconnected pads**. No individual DRC exclusions were added. The report lists five standard ignored check categories.

An independent comparison verified all 15 footprint values, footprint names and schematic UUID associations, and every pin on all 10 schematic nets. KiCad's Schematic Parity tab was not run in the standalone editor; the independent comparison is recorded in PCB-verification.json. The simplified schematic passed ERC with zero errors and warnings.

This design has not been fabricated or electrically tested. Measure the assembled oscillator period and check the 3.3 V rail during first power-up. Timing tolerance assumptions are documented in MP1-Notes.md.

## Included files

- Editable KiCad project, schematic, PCB, and project-specific libraries.
- ../docs/Schematic.pdf and the approved-parts BOM.
- Component-positions.csv (all top components, including the manually assembled USB plug).
- DRC.rpt and PCB-verification.json.
- previews/board-top.png: KiCad 3D render. The USB connector body is omitted because its custom footprint has no 3D model; its actual plated pads, slots and locating holes are present.
- previews/top-layout.svg and bottom-copper.svg: KiCad layer plots.
- fabrication/: top/bottom copper, solder mask and silkscreen Gerbers, board outline, separate plated/nonplated drill files, and drill maps/report. All share the same absolute origin; dimensions are millimetres. The plated shell slots use routed Excellon slots.

## Before ordering

Check the supplied Molex 0480370001 connector against a 1:1 print, including pin numbering, shell slots and board-edge position. It is a through-hole connector from the approved parts list; confirm it is the intended exception to the assignment's general surface-mount wording. All other parts are surface-mount. Use the supplied MPNs and inspect LED polarity during assembly. No order has been placed.

## Review of flagged issues

Review-of-Flagged-Issues.md records the earlier USB-edge, U1 clearance and silkscreen review. The current board has a rectangular outline, no decorative text, all routing on F.Cu, and aligned component references. Moving +3V3 and OUT to the top removed six vias in total. U1's remaining ground via moved 0.3 mm to clear the output escape. Component locations and circuit connections are unchanged. The board has 56 track segments and 9 ground vias. See checks/top-routing-verification.json for the current routing and label checks. The preview images and manufacturing files show the current board.
