import importlib.util
import sys
import types
from pathlib import Path
import unittest


def install_test_stubs():
    typer_module = types.ModuleType("typer")

    class Typer:
        def __init__(self, *args, **kwargs):
            pass

        def callback(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def command(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def add_typer(self, *args, **kwargs):
            return None

    class Context:
        pass

    class Exit(Exception):
        def __init__(self, code=0):
            super().__init__(code)
            self.code = code

    def Option(*args, **kwargs):
        return None

    typer_module.Typer = Typer
    typer_module.Context = Context
    typer_module.Exit = Exit
    typer_module.Option = Option

    pydantic_module = types.ModuleType("pydantic")

    class BaseModel:
        pass

    pydantic_module.BaseModel = BaseModel

    rich_module = types.ModuleType("rich")
    rich_console_module = types.ModuleType("rich.console")
    rich_table_module = types.ModuleType("rich.table")

    class Console:
        def __init__(self, *args, **kwargs):
            pass

    class Table:
        def __init__(self, *args, **kwargs):
            pass

    rich_console_module.Console = Console
    rich_table_module.Table = Table

    confluence_api_client_module = types.ModuleType("confluence_api_client")

    class ConfluenceApiClient:
        pass

    class ConfluenceConfig:
        def __init__(self, *args, **kwargs):
            pass

    confluence_api_client_module.ConfluenceApiClient = ConfluenceApiClient
    confluence_api_client_module.ConfluenceConfig = ConfluenceConfig

    sys.modules.setdefault("typer", typer_module)
    sys.modules.setdefault("pydantic", pydantic_module)
    sys.modules.setdefault("rich", rich_module)
    sys.modules.setdefault("rich.console", rich_console_module)
    sys.modules.setdefault("rich.table", rich_table_module)
    sys.modules.setdefault("confluence_api_client", confluence_api_client_module)


def load_confluence_cli():
    install_test_stubs()
    module_path = Path(__file__).resolve().parents[1] / "confluence_cli.py"
    spec = importlib.util.spec_from_file_location("confluence_cli", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load confluence_cli module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MarkdownToStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_confluence_cli()

    def render(self, markdown: str) -> str:
        return self.cli.markdown_to_storage(markdown, {})

    def test_paragraph_followed_by_heading(self):
        markdown = "Hello world\n\n# Title"
        expected = "<p>Hello world</p>\n<h1>Title</h1>"
        self.assertEqual(self.render(markdown), expected)

    def test_paragraph_followed_by_table(self):
        markdown = "Intro\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
        expected_table = (
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
        )
        expected = f"<p>Intro</p>\n{expected_table}"
        self.assertEqual(self.render(markdown), expected)


if __name__ == "__main__":
    unittest.main()
