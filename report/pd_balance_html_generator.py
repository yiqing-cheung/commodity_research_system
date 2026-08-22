from pathlib import Path

from report.pt_balance_html_generator import PTBalanceHTMLGenerator


class PDBalanceHTMLGenerator(PTBalanceHTMLGenerator):
    """Generate the palladium balance dashboard using the platinum layout."""

    def generate(self, output_file="site/pgm/pd_balance.html"):
        output = super().generate(output_file)
        html = Path(output).read_text(encoding="utf-8")
        replacements = (
            ("CHINA PLATINUM", "CHINA PALLADIUM"),
            ("China platinum", "China palladium"),
            ("pt-balance-user-estimates-v1", "pd-balance-user-estimates-v1"),
            ("71101100", "71102100"),
            ("71101910", "71102910"),
            ("71101990", "71102990"),
            ("铂", "钯"),
        )
        for old, new in replacements:
            html = html.replace(old, new)
        Path(output).write_text(html, encoding="utf-8")
        print(f"China palladium balance dashboard generated: {output}")
        return output


if __name__ == "__main__":
    PDBalanceHTMLGenerator(
        "data/pd_cn_import.csv",
        "data/pd_cn_export.csv",
        "data/gfex_PD_warehouse_receipt.csv",
    ).generate()
