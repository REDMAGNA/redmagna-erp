import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const outDir = "C:/Users/Magdiel Miron/Documents/Codex/2026-10-15/n/outputs";
const wb = Workbook.create();
const sh = wb.worksheets.add("Cotizador");
sh.showGridLines = false;
sh.freezePanes.freezeRows(10);

sh.getRange("A1:R1").merge();
sh.getRange("A1").values = [["COTIZADOR | REDMAGNA"]];
sh.getRange("A2:R2").merge();
sh.getRange("A2").values = [["Estimación comercial. Verifica costos, precios y tratamiento fiscal antes de enviar; no sustituye una factura CFDI emitida en FEL."]];
sh.getRange("A4:L5").values = [
  ["Cliente", "", "", "", "Folio", "", "Fecha", "", "Vigencia (días)", "", "", ""],
  ["Proyecto", "", "", "", "Moneda", "MXN", "Elaboró", "", "", "", "", ""]
];
sh.getRange("A6:L7").values = [["Subtotal", "", "IVA estimado", "", "Total estimado", "", "Costo interno", "", "Utilidad bruta", "", "Margen real", ""], ["", "", "", "", "", "", "", "", "", "", "", ""]];
for (const [a, b] of [["A6", "B6"], ["C6", "D6"], ["E6", "F6"], ["G6", "H6"], ["I6", "J6"], ["K6", "L6"], ["A7", "B7"], ["C7", "D7"], ["E7", "F7"], ["G7", "H7"], ["I7", "J7"], ["K7", "L7"]]) sh.getRange(`${a}:${b}`).merge();
sh.getRange("A7").formulas = [['=IF(COUNT(L11:L40)=0,"",SUM(L11:L40))']];
sh.getRange("C7").formulas = [['=IF(COUNT(N11:N40)=0,"",SUM(N11:N40))']];
sh.getRange("E7").formulas = [['=IF(COUNT(O11:O40)=0,"",SUM(O11:O40))']];
sh.getRange("G7").formulas = [['=IF(COUNT(P11:P40)=0,"",SUM(P11:P40))']];
sh.getRange("I7").formulas = [['=IF(COUNT(Q11:Q40)=0,"",SUM(Q11:Q40))']];
sh.getRange("K7").formulas = [['=IF(OR(A7="",A7=0,I7=""),"",I7/A7)']];
sh.getRange("A9:R9").merge();
sh.getRange("A9").values = [["Captura el costo unitario y margen objetivo para sugerir precio. Puedes sustituirlo con un precio manual; el descuento se aplica después. Ingresa la tasa de IVA que corresponda a cada partida."]];
const headers = ["No.", "Tipo", "SKU / clave", "Concepto y alcance", "Cantidad", "Costo unitario", "Margen objetivo", "Precio sugerido", "Precio manual", "Descuento", "Precio final", "Subtotal", "IVA %", "IVA", "Total c/IVA", "Costo total", "Utilidad bruta", "Margen real"];
sh.getRange("A10:R10").values = [headers];
const data = Array.from({ length: 30 }, (_, n) => [n + 1, "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]);
sh.getRange("A11:R40").values = data;
const cols = {
  H: i => `=IF(OR(D${i}="",F${i}="",G${i}=""),"",IF(OR(G${i}<0,G${i}>=1),"",F${i}/(1-G${i})))`,
  K: i => `=IF(D${i}="","",IF(AND(I${i}="",H${i}=""),"",IF(I${i}<>"",I${i},H${i})*(1-IF(J${i}="",0,J${i}))))`,
  L: i => `=IF(OR(D${i}="",E${i}="",K${i}=""),"",E${i}*K${i})`,
  N: i => `=IF(OR(L${i}="",M${i}=""),"",L${i}*M${i})`,
  O: i => `=IF(L${i}="","",L${i}+IF(N${i}="",0,N${i}))`,
  P: i => `=IF(OR(D${i}="",E${i}="",F${i}=""),"",E${i}*F${i})`,
  Q: i => `=IF(OR(L${i}="",P${i}=""),"",L${i}-P${i})`,
  R: i => `=IF(OR(Q${i}="",L${i}="",L${i}=0),"",Q${i}/L${i})`
};
for (const [col, formula] of Object.entries(cols)) sh.getRange(`${col}11:${col}40`).formulas = data.map((_, n) => [formula(n + 11)]);
sh.getRange("B11:B40").dataValidation = { rule: { type: "list", values: ["Equipo", "Material", "Instalación", "Servicio", "Otro"] } };
sh.getRange("G11:G40").dataValidation = { rule: { type: "decimal", operator: "between", formula1: 0, formula2: 0.99 } };
sh.getRange("J11:J40").dataValidation = { rule: { type: "decimal", operator: "between", formula1: 0, formula2: 1 } };
sh.getRange("M11:M40").dataValidation = { rule: { type: "decimal", operator: "between", formula1: 0, formula2: 1 } };

sh.getRange("A1:R1").format = { fill: "#12304A", font: { bold: true, color: "#FFFFFF", size: 16 }, verticalAlignment: "center" };
sh.getRange("A1:R1").format.rowHeight = 30;
sh.getRange("A2:R2").format = { font: { color: "#526477", italic: true, size: 10 }, wrapText: true };
sh.getRange("A2:R2").format.rowHeight = 30;
sh.getRange("A4:L5").format = { font: { size: 10, color: "#263746" } };
for (const r of ["A4:A5", "E4:E5", "G4:G5", "I4:I4"]) sh.getRange(r).format.font = { bold: true, color: "#526477" };
sh.getRange("B4:D4").merge();
sh.getRange("B5:D5").merge();
sh.getRange("H4").values = [[new Date()]];
sh.getRange("H4").setNumberFormat("dd-mmm-yyyy");
for (const r of ["B4:D5", "F4:F5", "H4:H5", "J4"]) sh.getRange(r).format = { fill: "#EAF2F8", font: { color: "#1565C0" } };
sh.getRange("A6:L6").format = { fill: "#EAF2F8", font: { bold: true, color: "#12304A" } };
sh.getRange("A7:L7").format = { fill: "#F4F8FB", font: { bold: true, color: "#12304A", size: 12 } };
for (const r of ["A7:A7", "C7:C7", "E7:E7", "G7:G7", "I7:I7"]) sh.getRange(r).setNumberFormat('$#,##0.00;($#,##0.00);-');
sh.getRange("K7").setNumberFormat("0.0%");
sh.getRange("A9:R9").format = { font: { color: "#526477", italic: true, size: 10 }, wrapText: true };
sh.getRange("A9:R9").format.rowHeight = 34;
sh.getRange("A10:R10").format = { fill: "#12304A", font: { bold: true, color: "#FFFFFF", size: 9 }, wrapText: true, verticalAlignment: "center" };
sh.getRange("A10:R10").format.rowHeight = 34;
sh.getRange("A11:R40").format = { font: { size: 10, color: "#222222" }, verticalAlignment: "center" };
sh.getRange("B11:G40").format.font = { color: "#1565C0" };
sh.getRange("I11:J40").format.font = { color: "#1565C0" };
sh.getRange("M11:M40").format.font = { color: "#1565C0" };
sh.getRange("A10:R40").format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EA" } };
sh.getRange("A10:R10").format.borders = { bottom: { style: "medium", color: "#0E7490" } };
for (const [r, fmt] of Object.entries({
  "E11:F40": '$#,##0.00;($#,##0.00);-', "G11:G40": "0.0%", "H11:I40": '$#,##0.00;($#,##0.00);-',
  "J11:J40": "0.0%", "K11:L40": '$#,##0.00;($#,##0.00);-', "M11:M40": "0.0%",
  "N11:Q40": '$#,##0.00;($#,##0.00);-', "R11:R40": "0.0%"
})) sh.getRange(r).setNumberFormat(fmt);
const widths = { A: 42, B: 110, C: 112, D: 230, E: 76, F: 112, G: 95, H: 112, I: 112, J: 83, K: 112, L: 112, M: 76, N: 102, O: 115, P: 112, Q: 112, R: 82 };
for (const [c, w] of Object.entries(widths)) sh.getRange(`${c}:${c}`).format.columnWidthPx = w;
sh.getRange("A11:A40").format.horizontalAlignment = "center";
sh.getRange("E11:Q40").format.horizontalAlignment = "right";
sh.getRange("B11:D40").format.horizontalAlignment = "left";
sh.getRange("R11:R40").format.horizontalAlignment = "right";

// Smoke-check price, discount, IVA, cost and margin with temporary inputs.
sh.getRange("D11:G11").values = [["Prueba temporal", 2, 100, 0.25]];
sh.getRange("J11").values = [[0.10]];
sh.getRange("M11").values = [[0.16]];
const tested = sh.getRange("H11:R11").values[0];
const expected = { H: 133.33333333333334, K: 120, L: 240, N: 38.4, O: 278.4, P: 200, Q: 40, R: 1 / 6 };
const idx = { H: 0, K: 3, L: 4, N: 6, O: 7, P: 8, Q: 9, R: 10 };
for (const [col, value] of Object.entries(expected)) {
  if (Math.abs(Number(tested[idx[col]]) - value) > 0.000001) throw new Error(`Calculation check failed at ${col}11: ${tested[idx[col]]}`);
}
// Remove test values so the delivered workbook opens as a clean template.
sh.getRange("D11:G11").clear({ applyTo: "contents" });
sh.getRange("J11").clear({ applyTo: "contents" });
sh.getRange("M11").clear({ applyTo: "contents" });
await wb.recalculate();
const values = sh.getRange("A1:R40").values;
const errors = [];
for (let r = 0; r < values.length; r++) for (let c = 0; c < values[r].length; c++) {
  if (typeof values[r][c] === "string" && /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!)/.test(values[r][c])) errors.push({ row: r + 1, col: c + 1, value: values[r][c] });
}
const preview = await wb.render({ sheetName: "Cotizador", range: "A1:R18", scale: 1, format: "png" });
await fs.writeFile("C:/Users/Magdiel Miron/Documents/Codex/2026-10-15/n/work/sites/redmagna-erp/tools/redmagna-cotizador-preview.png", new Uint8Array(await preview.arrayBuffer()));
const xlsx = await SpreadsheetFile.exportXlsx(wb);
const xlsxPath = `${outDir}/redmagna-cotizador.xlsx`;
await xlsx.save(xlsxPath);
const reopened = await SpreadsheetFile.importXlsx(new Uint8Array(await fs.readFile(xlsxPath)));
const reopenedSheet = reopened.worksheets.getItem("Cotizador");
if (!reopenedSheet) throw new Error("Export verification failed: Cotizador sheet is missing.");
const exportedFormulas = reopenedSheet.getRange("H11:R40").formulas.flat().filter(Boolean).length;
if (exportedFormulas !== 240) throw new Error(`Export verification failed: expected 240 formulas, found ${exportedFormulas}.`);
await fs.rm(`${xlsxPath}.inspect.ndjson`, { force: true });
console.log(JSON.stringify({ errors, tested, exportedFormulas, summary: sh.getRange("A6:L7").values, sampleFormulas: sh.getRange("H11:R11").formulas }));
