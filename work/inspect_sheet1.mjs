import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "D:/work/铂钯/铂数据/铂钯精简版 - 0720.xlsx";
const input = await FileBlob.load(sourcePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 6000 });
console.log("SHEETS");
console.log(sheets.ndjson);
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 12,
  tableMaxCols: 16,
  tableMaxCellChars: 100,
});
console.log("SUMMARY");
console.log(summary.ndjson);
const sheet = workbook.worksheets.getItemAt(0);
const used = sheet.getUsedRange();
console.log("USED_RANGE", used.address);
const values = used.values;
const formulas = used.formulas;
const populatedRows = values.map((row, index) => ({
  row: index + 1,
  values: row,
  formulas: formulas[index],
})).filter(item => item.values.some(value => value !== null && value !== "") || item.formulas.some(value => value));
console.log("POPULATED_ROWS");
console.log(JSON.stringify(populatedRows));
const preview = await workbook.render({ sheetName: sheet.name, range: "A1:P45", scale: 1.5, format: "png" });
await fs.writeFile("work/sheet1_preview.png", new Uint8Array(await preview.arrayBuffer()));
const previewBottom = await workbook.render({ sheetName: sheet.name, range: "A46:P118", scale: 1.2, format: "png" });
await fs.writeFile("work/sheet1_preview_bottom.png", new Uint8Array(await previewBottom.arrayBuffer()));
