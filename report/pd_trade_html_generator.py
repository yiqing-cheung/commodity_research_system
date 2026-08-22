from pathlib import Path

from report.pt_trade_html_generator import PTTradeHTMLGenerator


class PDTradeHTMLGenerator(PTTradeHTMLGenerator):
    """Generate the interactive China palladium import/export dashboard."""

    def __init__(self, import_csv, export_csv, template_file=None):
        super().__init__(
            import_csv=import_csv,
            export_csv=export_csv,
            template_file=(
                Path(template_file)
                if template_file
                else Path(__file__).with_name("pd_trade_template.html")
            ),
        )

