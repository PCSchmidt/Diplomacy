/* Schematic board geometry.
 *
 * MIT — see viewer/LICENSE. These coordinates are authored for this project, not
 * extracted from the GPL jDip map that ships with the `diplomacy` package. That
 * separation is what keeps the viewer permissively licensed; see ../NOTICE.
 *
 * The layout is geographically suggestive rather than cartographic: provinces sit
 * where a Diplomacy player expects them relative to their neighbours, on a 1000x760
 * grid. The board is the least differentiating panel in this viewer, so it aims to
 * be legible and honest rather than pretty.
 */

export const POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"];

export const POWER_COLORS = {
  AUSTRIA: "#c2453c",
  ENGLAND: "#6b4fa8",
  FRANCE:  "#3a7bbf",
  GERMANY: "#4a4a4a",
  ITALY:   "#3f9160",
  RUSSIA:  "#b8862b",
  TURKEY:  "#c98b2e",
  NONE:    "#9aa0a6",
};

// province -> [x, y, kind]  kind: l=land, c=coastal, w=water, x=impassable
export const PROVINCES = {
  // --- Atlantic & British Isles ---
  NAO: [110,  70, "w"], NWG: [300,  40, "w"], BAR: [560,  30, "w"],
  CLY: [250, 150, "c"], EDI: [280, 175, "c"], LVP: [245, 200, "c"],
  YOR: [290, 215, "c"], WAL: [235, 245, "c"], LON: [300, 250, "c"],
  NTH: [370, 175, "w"], IRI: [175, 235, "w"], ENG: [275, 300, "w"],
  MAO: [ 90, 340, "w"], WES: [265, 470, "w"], NAF: [200, 545, "c"],
  TUN: [345, 545, "c"],
  // --- Scandinavia & Baltic ---
  NWY: [430,  95, "c"], SWE: [500, 110, "c"], FIN: [575,  90, "c"],
  STP: [680,  85, "c"], DEN: [455, 195, "c"], SKA: [440, 155, "w"],
  BAL: [530, 210, "w"], BOT: [560, 150, "w"], LVN: [640, 175, "c"],
  PRU: [560, 260, "c"], BER: [500, 265, "c"], KIE: [450, 255, "c"],
  HEL: [405, 205, "w"], HOL: [385, 250, "c"], BEL: [345, 285, "c"],
  RUH: [420, 295, "l"], MUN: [455, 320, "l"],
  // --- France & Iberia ---
  PIC: [320, 315, "c"], BRE: [255, 335, "c"], PAR: [320, 350, "l"],
  BUR: [385, 350, "l"], GAS: [270, 395, "c"], MAR: [345, 415, "c"],
  SPA: [200, 440, "c"], POR: [130, 430, "c"], LYO: [320, 460, "w"],
  // --- Central Europe ---
  SIL: [540, 300, "l"], WAR: [615, 275, "l"], GAL: [615, 330, "l"],
  BOH: [510, 330, "l"], TYR: [470, 365, "l"], VIE: [540, 375, "l"],
  SWI: [430, 370, "x"],   // impassable
  BUD: [595, 385, "l"], TRI: [520, 420, "c"],
  // --- Italy & Mediterranean ---
  PIE: [415, 415, "c"], VEN: [460, 425, "c"], TUS: [445, 460, "c"],
  ROM: [470, 495, "c"], NAP: [510, 530, "c"], APU: [520, 490, "c"],
  TYS: [420, 510, "w"], ION: [500, 590, "w"], ADR: [530, 470, "w"],
  ALB: [575, 465, "c"], GRE: [600, 520, "c"], SER: [600, 435, "l"],
  BUL: [665, 450, "c"], RUM: [680, 390, "c"], AEG: [660, 545, "w"],
  EAS: [750, 580, "w"],
  // --- Russia, Black Sea & Turkey ---
  MOS: [740, 210, "l"], SEV: [760, 330, "c"], UKR: [690, 305, "l"],
  BLA: [730, 415, "w"], ANK: [750, 470, "c"], CON: [690, 490, "c"],
  SMY: [730, 525, "c"], ARM: [820, 455, "c"], SYR: [830, 530, "c"],
};

// Supply centres (34 on the standard map).
export const SUPPLY_CENTERS = new Set([
  "ANK","BEL","BER","BRE","BUD","BUL","CON","DEN","EDI","GRE","HOL","KIE",
  "LON","LVP","MAR","MOS","MUN","NAP","NWY","PAR","POR","ROM","RUM","SER","SEV",
  "SMY","SPA","STP","SWE","TRI","TUN","VEN","VIE","WAR",
]);

/** Strip a coast qualifier: "STP/SC" -> "STP". */
export function baseProvince(name) {
  return String(name || "").split("/")[0].toUpperCase().trim();
}

/** Parse "F STP/SC" or "A PAR" into {type, province}. */
export function parseUnit(unit) {
  const parts = String(unit).trim().split(/\s+/);
  return { type: parts[0], province: baseProvince(parts[1]) };
}
