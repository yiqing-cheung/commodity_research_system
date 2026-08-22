import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("D:/work/铂钯/铂数据/铂钯精简版 - 0720.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItemAt(0);
const used = sheet.getUsedRange();
const values = used.values;
const formulas = used.formulas;

const clean = value => typeof value === "number" && Number.isFinite(value) ? value : null;
const rows = values.map((row, i) => ({ excelRow: i + 1, row, formulas: formulas[i] }));
const annual = rows.filter(({ row }) => Number.isInteger(row[0]) && row[0] >= 2020 && row[0] <= 2030)
  .map(({ excelRow, row }) => ({
    excelRow, year: row[0], imports: clean(row[1]), exports: clean(row[4]), netImports: clean(row[7]),
    inventory: clean(row[11]), inventoryChange: clean(row[12]), apparentConsumption: clean(row[13]),
    netImportYoY: clean(row[9]), consumptionYoY: clean(row[15]),
  }));
const monthly = rows.filter(({ row }) => {
  const code = Number(row[0]);
  return Number.isInteger(code) && code >= 202001 && code <= 203012;
}).map(({ excelRow, row }) => ({
  excelRow, period: String(row[0]), imports: clean(row[1]), exports: clean(row[4]), netImports: clean(row[7]),
  netImportYoY: clean(row[8]), netImportYtdYoY: clean(row[9]), netImportMoM: clean(row[10]),
  inventory: clean(row[11]), inventoryChange: clean(row[12]), apparentConsumption: clean(row[13]),
  consumptionYoY: clean(row[14]), consumptionYtdYoY: clean(row[15]),
}));
const actual = monthly.filter(row => row.imports !== null && row.exports !== null);
const yearlyFromMonths = {};
for (const row of actual) {
  const year = row.period.slice(0, 4);
  yearlyFromMonths[year] ??= { months: 0, imports: 0, exports: 0, netImports: 0, apparentConsumption: 0 };
  const item = yearlyFromMonths[year];
  item.months += 1;
  item.imports += row.imports;
  item.exports += row.exports;
  item.netImports += row.netImports ?? row.imports - row.exports;
  item.apparentConsumption += row.apparentConsumption ?? 0;
}
const errors = [];
for (let r = 0; r < values.length; r++) for (let c = 0; c < values[r].length; c++) {
  if (typeof values[r][c] === "string" && /^#(DIV\/0!|NAME\?|REF!|VALUE!|N\/A)/.test(values[r][c])) {
    errors.push({ row: r + 1, col: c + 1, value: values[r][c], formula: formulas[r]?.[c] || null });
  }
}
console.log(JSON.stringify({
  sheet: sheet.name,
  usedRange: used.address,
  headers: values.slice(14, 17),
  annual,
  yearlyFromMonths,
  latestActual: actual.slice(-12),
  forecast: monthly.filter(row => row.imports === null && row.period >= "202607"),
  notes: values.slice(112, 118).map((row, i) => ({ row: i + 113, text: row.filter(v => typeof v === "string" && v).join(" ") })),
  errorsCount: errors.length,
  errors: errors.slice(0, 50),
}, null, 2));
