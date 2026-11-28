from rich.console import Console
from rich.table import Table
from rich.text import Text

# Markup is off, so text from Central such as a "[cut]" log line prints as it is. Style comes only from Text.
# Rich drops colour when the output is not a terminal or NO_COLOR is set.
console = Console(highlight=False, markup=False, soft_wrap=True)
error_console = Console(stderr=True, highlight=False, markup=False, soft_wrap=True)

STATUS_STYLES = {
	"Active": "green",
	"Succeeded": "green",
	"Success": "green",
	"Failed": "red",
	"Failure": "red",
	"Validating": "yellow",
	"Provisioning": "yellow",
	"Building": "yellow",
	"Releasing": "yellow",
	"Running": "yellow",
	"Queued": "dim",
	"Superseded": "dim",
	"Disabled": "dim",
}


def get_status_text(status: str | None) -> Text:
	return Text(status or "-", style=STATUS_STYLES.get(status or "", ""))


def print_table(headers: list[str], rows: list[list[str | Text]]) -> None:
	table = Table(box=None, header_style="bold", pad_edge=False)
	for header in headers:
		table.add_column(header)
	for row in rows:
		table.add_row(*row)
	console.print(table)


def print_success(message: str) -> None:
	console.print(Text(message, style="green"))


def print_warning(message: str) -> None:
	console.print(Text.assemble(("Warning: ", "bold yellow"), message))


def print_error(message: str) -> None:
	error_console.print(Text.assemble(("Error: ", "bold red"), message))
