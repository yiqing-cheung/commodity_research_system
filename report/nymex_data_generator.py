"""Generate all NYMEX inventory and delivery charts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.nymex_inventory import (
    DEFAULT_YEARS,
    NYMEXInventoryAnalyzer,
    SEASONAL_METRICS,
)


class NYMEXReportData:
    def __init__(
        self,
        data_file: str | Path = "data/pgm_receipt_nymex.csv",
        chart_folder: str | Path = "report_data/charts",
        years=DEFAULT_YEARS,
    ) -> None:
        self.data_file = Path(data_file)
        self.chart_folder = Path(chart_folder)
        self.years = tuple(years)

    def generate(self) -> list[Path]:
        self.chart_folder.mkdir(parents=True, exist_ok=True)
        analyzer = NYMEXInventoryAnalyzer(
            file_path=self.data_file,
            years=self.years,
        )
        analyzer.load_data()

        outputs: list[Path] = []
        for metric in SEASONAL_METRICS:
            stem = f"NYMEX_{metric}_seasonal"
            outputs.append(
                analyzer.plot_seasonal_png(
                    metric,
                    self.chart_folder / f"{stem}.png",
                )
            )
            outputs.append(
                analyzer.plot_seasonal_html(
                    metric,
                    self.chart_folder / f"{stem}.html",
                )
            )

        outputs.append(
            analyzer.plot_delivery_png(
                self.chart_folder / "NYMEX_delivery_1y.png"
            )
        )
        outputs.append(
            analyzer.plot_delivery_html(
                self.chart_folder / "NYMEX_delivery_1y.html"
            )
        )

        print("NYMEX charts generated:")
        for output in outputs:
            print(f"  {output.resolve()}")
        return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NYMEX PGM charts")
    parser.add_argument(
        "--data-file",
        default="data/pgm_receipt_nymex.csv",
    )
    parser.add_argument(
        "--chart-folder",
        default="report_data/charts",
    )
    args = parser.parse_args()

    NYMEXReportData(
        data_file=args.data_file,
        chart_folder=args.chart_folder,
    ).generate()


if __name__ == "__main__":
    main()
