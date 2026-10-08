"""字体网格、合并布局和上游检查的契约测试。"""

import json

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from rich.text import Text
from typer.testing import CliRunner

from scripts import merge_terminal_fonts as merge
from scripts import terminal_font_sources as sources


def fixture_font(style: str, latin: bool) -> TTFont:
    """建立含宽字形、中文、连字和附加符锚点的最小来源。"""
    characters = set("".join(merge.SHAPING_SAMPLES) + "中文测试á")
    cmap = {ord(char): f"u{ord(char):04X}" for char in sorted(characters)}
    names = [".notdef", *cmap.values(), "arrow"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap(cmap)
    glyphs, metrics = {}, {}
    for name in names:
        width = 1200 if name == "arrow" else (600 if latin else 500)
        if name in [cmap[ord(char)] for char in "中文测试"]:
            width = 1000
        if name == cmap[0x301]:
            width = 0
        pen = TTGlyphPen(None)
        if name != cmap[ord(" ")]:
            ink = 540 if name == cmap[ord("A")] else 400
            pen.moveTo((50, 0))
            pen.lineTo((50 + ink, 0))
            pen.lineTo((50 + ink, 700))
            pen.lineTo((50, 700))
            pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (width, 50)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=965, descent=-215, lineGap=70)
    ps = f"Lilex-{style}" if latin else merge.STYLES[style]
    builder.setupNameTable({"familyName": ps, "styleName": style, "psName": ps})
    builder.setupOS2(
        sTypoAscender=965, sTypoDescender=-215, usWinAscent=965, usWinDescent=215
    )
    builder.setupPost()
    builder.setupMaxp()
    addOpenTypeFeaturesFromString(
        builder.font,
        f"""
        feature calt {{ sub {cmap[ord("-")]} {cmap[ord(">")]} by arrow; }} calt;
        markClass {cmap[0x301]} <anchor 0 700> @TOP;
        feature mark {{ pos base {cmap[ord("a")]} <anchor 300 700> mark @TOP; }} mark;
    """,
    )
    builder.font.recalcTimestamp = False
    builder.font["head"].created = builder.font["head"].modified = 3800000000
    return builder.font


def bounds(font: TTFont, char: str) -> tuple:
    """读取真实轮廓边界。"""
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[font.getBestCmap()[ord(char)]].draw(pen)
    return pen.bounds


def test_sidebearings_preserve_height_and_fill_grid():
    font = fixture_font("Regular", True)
    before = bounds(font, "M")
    counts = merge.fit_sidebearings(font, 5 / 6)
    after = bounds(font, "M")
    assert after[2] - after[0] == before[2] - before[0] == 400
    assert after[1::2] == before[1::2]
    assert bounds(font, "A") == (10, 0, 490, 700)
    assert font["hmtx"][font.getBestCmap()[ord("A")]][0] == 500
    assert font["hmtx"]["arrow"][0] == 1000
    assert counts["ligature_uniform"] > 0
    anchor = (
        font["GPOS"]
        .table.LookupList.Lookup[0]
        .SubTable[0]
        .BaseArray.BaseRecord[0]
        .BaseAnchor[0]
    )
    assert anchor.XCoordinate == 300


def test_build_repeatable_and_install_conflict(tmp_path):
    latin_dir = tmp_path / "latin"
    latin_dir.mkdir()
    collection = TTCollection()
    collection.fonts = []
    for style in merge.STYLES:
        fixture_font(style, True).save(latin_dir / f"Lilex-{style}.ttf")
        collection.fonts.append(fixture_font(style, False))
    sarasa = tmp_path / "Sarasa-SuperTTC.ttc"
    collection.save(sarasa)
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        result = CliRunner().invoke(
            merge.app,
            [
                "--sarasa",
                str(sarasa),
                "--lilex-dir",
                str(latin_dir),
                "--output-dir",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output + str(result.exception)
    reports = [
        json.loads((output / "build-report.json").read_text()) for output in outputs
    ]
    assert reports[0] == reports[1]
    assert len(reports[0]["faces"]) == 4
    for face in reports[0]["faces"]:
        assert (outputs[0] / face["file"]).read_bytes() == (
            outputs[1] / face["file"]
        ).read_bytes()
        with TTFont(outputs[0] / face["file"]) as font:
            assert font["name"].getDebugName(1) == reports[0]["family"]
            assert font["hmtx"][font.getBestCmap()[ord("中")]][0] == 1000
    for name in ("Lilex.txt", "Sarasa-Gothic.txt"):
        assert "open font license" in (outputs[0] / name).read_text().lower()
    assert reports[0]["family"] in (outputs[0] / "ghostty.font.conf").read_text()
    installed = tmp_path / "installed"
    merge.install_fonts(outputs[0], installed)
    merge.install_fonts(outputs[0], installed)
    target = next(installed.glob("*.ttf"))
    target.write_bytes(b"different")
    with pytest.raises(ValueError, match="内容不同"):
        merge.install_fonts(outputs[0], installed)
    result = CliRunner().invoke(
        merge.app,
        [
            "--sarasa",
            str(sarasa),
            "--lilex-dir",
            str(latin_dir),
            "--output-dir",
            str(outputs[0]),
        ],
    )
    assert result.exit_code != 0


def test_upstream_change_and_lookup_failure(monkeypatch):
    def lookup(font, latest=False):
        if latest:
            return {"id": font["observed_latest"], "tag_name": "smaller-number"}
        return {
            "assets": [{"name": font["asset"], "digest": "sha256:" + font["sha256"]}]
        }

    monkeypatch.setattr(sources, "release", lookup)
    assert CliRunner().invoke(sources.app, ["check"]).exit_code == 0
    monkeypatch.setattr(
        sources,
        "release",
        lambda font, latest=False: (
            {"id": 0, "tag_name": "new"} if latest else lookup(font)
        ),
    )
    result = CliRunner().invoke(sources.app, ["check"])
    assert result.exit_code == 1 and "发现新发布" in result.output
    monkeypatch.setattr(
        sources,
        "release",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert CliRunner().invoke(sources.app, ["check"]).exit_code == 1
    font = sources.load_manifest(sources.DEFAULT_MANIFEST)[0]
    with pytest.raises(ValueError, match="摘要发生变化"):
        sources.approved_asset(
            font, {"assets": [{"name": font["asset"], "digest": "wrong"}]}
        )


def test_cli_help_and_invalid_paths():
    for app, args in ((merge.app, ["--help"]), (sources.app, ["fetch", "--help"])):
        result = CliRunner().invoke(app, args, env={"FORCE_COLOR": "1"})
        assert "--output-dir" in Text.from_ansi(result.output).plain
    assert (
        CliRunner().invoke(merge.app, ["--sarasa", "/missing/font.ttc"]).exit_code != 0
    )


def test_fetch_checks_bytes_and_extracts_only_selected_members(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile

    fonts = sources.load_manifest(sources.DEFAULT_MANIFEST)
    archives = {}
    for font in fonts:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for member in font["members"]:
                archive.writestr(member, b"font fixture")
            archive.writestr("../../unexpected", b"excluded")
        archives[font["asset"]] = buffer.getvalue()
        font["sha256"] = hashlib.sha256(buffer.getvalue()).hexdigest()
    monkeypatch.setattr(sources, "load_manifest", lambda path: fonts)
    monkeypatch.setattr(
        sources,
        "release",
        lambda font: {
            "assets": [
                {
                    "name": font["asset"],
                    "digest": "sha256:" + font["sha256"],
                    "browser_download_url": f"https://github.com/{font['repository']}/releases/download/{font['tag']}/{font['asset']}",
                }
            ]
        },
    )
    monkeypatch.setattr(
        sources,
        "urlopen",
        lambda url, timeout: io.BytesIO(archives[url.rsplit("/", 1)[1]]),
    )
    output = tmp_path / "sources"
    result = CliRunner().invoke(sources.app, ["fetch", "--output-dir", str(output)])
    assert result.exit_code == 0, result.exception
    assert (output / "lilex/Lilex-Regular.ttf").read_bytes() == b"font fixture"
    assert not (tmp_path / "unexpected").exists()
    assert (
        CliRunner()
        .invoke(sources.app, ["fetch", "--output-dir", str(output)])
        .exit_code
        != 0
    )
    archives[fonts[0]["asset"]] = b"corrupt"
    output = tmp_path / "bad"
    result = CliRunner().invoke(sources.app, ["fetch", "--output-dir", str(output)])
    assert result.exit_code != 0
    assert not output.exists()
