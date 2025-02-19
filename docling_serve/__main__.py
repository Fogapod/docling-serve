import importlib
import logging
import platform
import sys
import warnings
from typing import Annotated, Any, Union

import typer
import uvicorn
from rich.console import Console

from docling_serve.settings import docling_serve_settings, uvicorn_settings

warnings.filterwarnings(action="ignore", category=UserWarning, module="pydantic|torch")
warnings.filterwarnings(action="ignore", category=FutureWarning, module="easyocr")


err_console = Console(stderr=True)
console = Console()

app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
)

logger = logging.getLogger(__name__)


def version_callback(value: bool) -> None:
    if value:
        docling_serve_version = importlib.metadata.version("docling_serve")
        docling_version = importlib.metadata.version("docling")
        docling_core_version = importlib.metadata.version("docling-core")
        docling_ibm_models_version = importlib.metadata.version("docling-ibm-models")
        docling_parse_version = importlib.metadata.version("docling-parse")
        platform_str = platform.platform()
        py_impl_version = sys.implementation.cache_tag
        py_lang_version = platform.python_version()
        console.print(f"Docling Serve version: {docling_serve_version}")
        console.print(f"Docling version: {docling_version}")
        console.print(f"Docling Core version: {docling_core_version}")
        console.print(f"Docling IBM Models version: {docling_ibm_models_version}")
        console.print(f"Docling Parse version: {docling_parse_version}")
        console.print(f"Python: {py_impl_version} ({py_lang_version})")
        console.print(f"Platform: {platform_str}")
        raise typer.Exit()


@app.callback()
def callback(
    version: Annotated[
        Union[bool, None],
        typer.Option(
            "--version", help="Show the version and exit.", callback=version_callback
        ),
    ] = None,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Set the verbosity level. -v for info logging, -vv for debug logging.",
        ),
    ] = 0,
) -> None:
    if verbose == 0:
        logging.basicConfig(level=logging.WARNING)
    elif verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif verbose == 2:
        logging.basicConfig(level=logging.DEBUG)


def _run(
    *,
    command: str,
) -> None:
    server_type = "development" if command == "dev" else "production"

    console.print(f"Starting {server_type} server 🚀")

    url = f"http://{uvicorn_settings.host}:{uvicorn_settings.port}"
    url_docs = f"{url}/docs"
    url_ui = f"{url}/ui"

    console.print("")
    console.print(f"Server started at [link={url}]{url}[/]")
    console.print(f"Documentation at [link={url_docs}]{url_docs}[/]")
    if docling_serve_settings.enable_ui:
        console.print(f"UI at [link={url_ui}]{url_ui}[/]")

    if command == "dev":
        console.print("")
        console.print(
            "Running in development mode, for production use: "
            "[bold]docling-serve run[/]",
        )

    console.print("")
    console.print("Logs:")

    uvicorn.run(
        app="docling_serve.app:create_app",
        factory=True,
        host=uvicorn_settings.host,
        port=uvicorn_settings.port,
        reload=uvicorn_settings.reload,
        workers=uvicorn_settings.workers,
        root_path=uvicorn_settings.root_path,
        proxy_headers=uvicorn_settings.proxy_headers,
    )


@app.command()
def dev(
    *,
    # uvicorn options
    host: Annotated[
        str,
        typer.Option(
            help=(
                "The host to serve on. For local development in localhost "
                "use [blue]127.0.0.1[/blue]. To enable public access, "
                "e.g. in a container, use all the IP addresses "
                "available with [blue]0.0.0.0[/blue]."
            )
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(help="The port to serve on."),
    ] = uvicorn_settings.port,
    reload: Annotated[
        bool,
        typer.Option(
            help=(
                "Enable auto-reload of the server when (code) files change. "
                "This is [bold]resource intensive[/bold], "
                "use it only during development."
            )
        ),
    ] = True,
    root_path: Annotated[
        str,
        typer.Option(
            help=(
                "The root path is used to tell your app that it is being served "
                "to the outside world with some [bold]path prefix[/bold] "
                "set up in some termination proxy or similar."
            )
        ),
    ] = uvicorn_settings.root_path,
    proxy_headers: Annotated[
        bool,
        typer.Option(
            help=(
                "Enable/Disable X-Forwarded-Proto, X-Forwarded-For, "
                "X-Forwarded-Port to populate remote address info."
            )
        ),
    ] = uvicorn_settings.proxy_headers,
    # docling options
    enable_ui: Annotated[bool, typer.Option(help="Enable the development UI.")] = True,
) -> Any:
    """
    Run a [bold]Docling Serve[/bold] app in [yellow]development[/yellow] mode. 🧪

    This is equivalent to [bold]docling-serve run[/bold] but with [bold]reload[/bold]
    enabled and listening on the [blue]127.0.0.1[/blue] address.

    Options can be set also with the corresponding ENV variable, with the exception
    of --enable-ui, --host and --reload.
    """

    uvicorn_settings.host = host
    uvicorn_settings.port = port
    uvicorn_settings.reload = reload
    uvicorn_settings.root_path = root_path
    uvicorn_settings.proxy_headers = proxy_headers

    docling_serve_settings.enable_ui = enable_ui

    _run(
        command="dev",
    )


@app.command()
def run(
    *,
    host: Annotated[
        str,
        typer.Option(
            help=(
                "The host to serve on. For local development in localhost "
                "use [blue]127.0.0.1[/blue]. To enable public access, "
                "e.g. in a container, use all the IP addresses "
                "available with [blue]0.0.0.0[/blue]."
            )
        ),
    ] = uvicorn_settings.host,
    port: Annotated[
        int,
        typer.Option(help="The port to serve on."),
    ] = uvicorn_settings.port,
    reload: Annotated[
        bool,
        typer.Option(
            help=(
                "Enable auto-reload of the server when (code) files change. "
                "This is [bold]resource intensive[/bold], "
                "use it only during development."
            )
        ),
    ] = uvicorn_settings.reload,
    workers: Annotated[
        Union[int, None],
        typer.Option(
            help=(
                "Use multiple worker processes. "
                "Mutually exclusive with the --reload flag."
            )
        ),
    ] = uvicorn_settings.workers,
    root_path: Annotated[
        str,
        typer.Option(
            help=(
                "The root path is used to tell your app that it is being served "
                "to the outside world with some [bold]path prefix[/bold] "
                "set up in some termination proxy or similar."
            )
        ),
    ] = uvicorn_settings.root_path,
    proxy_headers: Annotated[
        bool,
        typer.Option(
            help=(
                "Enable/Disable X-Forwarded-Proto, X-Forwarded-For, "
                "X-Forwarded-Port to populate remote address info."
            )
        ),
    ] = uvicorn_settings.proxy_headers,
    # docling options
    enable_ui: Annotated[
        bool, typer.Option(help="Enable the development UI.")
    ] = docling_serve_settings.enable_ui,
) -> Any:
    """
    Run a [bold]Docling Serve[/bold] app in [green]production[/green] mode. 🚀

    This is equivalent to [bold]docling-serve dev[/bold] but with [bold]reload[/bold]
    disabled and listening on the [blue]0.0.0.0[/blue] address.

    Options can be set also with the corresponding ENV variable, e.g. UVICORN_PORT
    or DOCLING_SERVE_ENABLE_UI.
    """

    uvicorn_settings.host = host
    uvicorn_settings.port = port
    uvicorn_settings.reload = reload
    uvicorn_settings.workers = workers
    uvicorn_settings.root_path = root_path
    uvicorn_settings.proxy_headers = proxy_headers

    docling_serve_settings.enable_ui = enable_ui

    _run(
        command="run",
    )


def main() -> None:
    app()


# Launch the CLI when calling python -m docling_serve
if __name__ == "__main__":

    main()
