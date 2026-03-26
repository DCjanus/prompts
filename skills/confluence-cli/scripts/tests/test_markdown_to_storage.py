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

    def Field(*args, default=None, **kwargs):
        return default

    pydantic_module.BaseModel = BaseModel
    pydantic_module.Field = Field

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
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MarkdownToStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_confluence_cli()

    def render(self, markdown: str) -> str:
        return self.cli.markdown_to_storage(markdown, {})

    def render_with_assets(self, markdown: str, **kwargs):
        attachment_map = {}
        rendered = self.cli.markdown_to_storage(markdown, attachment_map, **kwargs)
        return rendered, attachment_map

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

    def test_supports_lists_and_inline_formatting(self):
        markdown = (
            "1. **bold** item\n"
            "2. `inline` item\n\n"
            "- alpha\n"
            "- *beta*\n"
        )
        expected = (
            "<ol><li><p><strong>bold</strong> item</p></li><li><p><code>inline</code> item</p></li></ol>\n"
            "<ul><li><p>alpha</p></li><li><p><em>beta</em></p></li></ul>"
        )
        self.assertEqual(self.render(markdown), expected)

    def test_supports_fenced_code_blocks(self):
        markdown = "```text\nhello <world>\n```"
        expected = '<pre><code class="language-text">hello &lt;world&gt;\n</code></pre>'
        self.assertEqual(self.render(markdown), expected)

    def test_local_relative_links_become_attachments(self):
        markdown = "See [design](./design.md)."
        rendered, attachment_map = self.render_with_assets(
            markdown,
            page_id="123",
            base_url="https://confluence.example.com",
        )
        self.assertEqual(
            rendered,
            '<p>See <a href="https://confluence.example.com/download/attachments/123/design.md">design</a>.</p>',
        )
        self.assertEqual(attachment_map, {"design.md": "./design.md"})

    def test_local_images_become_attachment_macros(self):
        markdown = "![diagram](./diagram.png)"
        rendered, attachment_map = self.render_with_assets(markdown)
        self.assertEqual(
            rendered,
            '<p><ac:image ac:alt="diagram"><ri:attachment ri:filename="diagram.png" /></ac:image></p>',
        )
        self.assertEqual(attachment_map, {"diagram.png": "./diagram.png"})

    def test_strip_leading_title_heading(self):
        markdown = "# Report Title\n\n## Section\n\nBody"
        stripped = self.cli.strip_leading_title_heading(markdown)
        self.assertEqual(stripped, "## Section\n\nBody")

    def test_unsupported_construct_raises_error(self):
        with self.assertRaises(self.cli.ApiError) as ctx:
            self.render("<details><summary>x</summary>y</details>")
        self.assertIn("Unsupported Markdown", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
