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
    names = [".notdef", *cmap.values(), "arrow", *([] if latin else ["wide"])]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap(cmap)
    glyphs, metrics = {}, {}
    for name in names:
        width = 1200 if name == "arrow" else (600 if latin else 500)
        if name in [cmap[ord(char)] for char in "中文测试"]:
            width = 1000
        if name == "wide":
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
        """
        + ("" if latin else f"feature WWID {{ sub {cmap[ord('M')]} by wide; }} WWID;"),
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


def fixture_icons() -> TTFont:
    """包含 BMP、补充私用区、已有符号及空格的不同 UPEM 图标来源。"""
    builder = FontBuilder(2048, isTTF=True)
    cmap = {cp: f"icon{cp:X}" for cp in (0x20, 0xE606, 0xF030E, ord("中"))}
    names = [".notdef", *cmap.values()]
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap(cmap)
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        if name != cmap[0x20]:
            pen.moveTo((-100, -200))
            pen.lineTo((2100, -200))
            pen.lineTo((2100, 1800))
            pen.lineTo((-100, 1800))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (2048, -100) for name in names})
    builder.setupHorizontalHeader(ascent=1800, descent=-248)
    builder.setupNameTable(
        {"familyName": "Symbols Nerd Font Mono", "styleName": "Regular"}
    )
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.font.recalcTimestamp = False
    builder.font["head"].created = builder.font["head"].modified = 3800000000
    return builder.font


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


def test_icon_validation_rejects_missing_and_overflowing_glyphs(tmp_path):
    path = tmp_path / "icons.ttf"
    font = fixture_icons()
    font.save(path)
    with pytest.raises(ValueError, match="缺少 Nerd Fonts"):
        merge.verify_icons(path, {0xE606, 0xE73C}, {0xE606}, 2048)
    with pytest.raises(ValueError, match="图标越出单格"):
        merge.verify_icons(path, {0xE606}, {0xE606}, 2048)
    merge.fit_icons(font, 500, 965, -215)
    font["hhea"].ascent, font["hhea"].descent = 965, -215
    font.save(path)
    merge.verify_icons(path, {0xE606, 0xF030E}, {0xE606, 0xF030E}, 500)


def test_drop_wwid_preserves_characters_and_removes_unencoded_alternates():
    font = fixture_font("Regular", False)
    before = dict(font.getBestCmap())
    assert "wide" in font.getGlyphOrder()
    merge.subset_font(font, set(before), drop_features={"WWID"})
    assert font.getBestCmap() == before
    assert "wide" not in font.getGlyphOrder()
    assert "WWID" not in {
        r.FeatureTag for r in font["GSUB"].table.FeatureList.FeatureRecord
    }
    assert bounds(font, "M") == (50, 0, 450, 700)
    assert font["hmtx"][before[ord("中")]][0] == 1000


def test_icon_curve_control_points_fit_cell_after_rounding(tmp_path):
    font = fixture_icons()
    name = font.getBestCmap()[0xE606]
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.qCurveTo((2500, 1000), (2000, 0))
    pen.lineTo((0, 0))
    pen.closePath()
    font["glyf"][name] = pen.glyph()
    merge.fit_icons(font, 500, 965, -215)
    font["hhea"].ascent, font["hhea"].descent = 965, -215
    path = tmp_path / "curve.ttf"
    font.save(path)
    merge.verify_icons(path, {0xE606}, {0xE606}, 500)


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
    nerd_font = tmp_path / "SymbolsNerdFontMono-Regular.ttf"
    fixture_icons().save(nerd_font)
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        result = CliRunner().invoke(
            merge.app,
            [
                "--sarasa",
                str(sarasa),
                "--lilex-dir",
                str(latin_dir),
                "--nerd-font",
                str(nerd_font),
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
        assert face["file"] == f"DCjanusMonoSC-{face['style']}.ttf"
        assert (outputs[0] / face["file"]).read_bytes() == (
            outputs[1] / face["file"]
        ).read_bytes()
        with TTFont(outputs[0] / face["file"]) as font:
            assert (
                font["name"].getDebugName(1)
                == reports[0]["family"]
                == "DCjanus Mono SC"
            )
            assert reports[0]["build_id"] in font["name"].getDebugName(6)
            assert font["hmtx"][font.getBestCmap()[ord("中")]][0] == 1000
            assert bounds(font, "中") == bounds(
                fixture_font(face["style"], False), "中"
            )
            assert face["icons_added"] == 2
            assert face["icons_covered"] == 3
            assert face["icons_preserved"] == ["U+4E2D"]
            assert "wide" not in font.getGlyphOrder()
            for cp in (0xE606, 0xF030E):
                assert font["hmtx"][font.getBestCmap()[cp]][0] == 500
                left, bottom, right, top = bounds(font, chr(cp))
                assert 0 <= left < right <= 500
                assert -215 <= bottom < top <= 965
                assert (right - left) / (top - bottom) == pytest.approx(1.1, abs=0.005)
    for name in ("Lilex.txt", "Sarasa-Gothic.txt", "Nerd-Fonts.txt"):
        assert "open font license" in (outputs[0] / name).read_text().lower()
    assert reports[0]["family"] in (outputs[0] / "ghostty.font.conf").read_text()
    installed = tmp_path / "installed"
    merge.install_fonts(outputs[0], installed)
    merge.install_fonts(outputs[0], installed)
    target = next(installed.glob("*.ttf"))
    source = outputs[0] / target.name
    with TTFont(source) as updated:
        updated["name"].setName("Version 1.001", 5, 3, 1, 0x409)
        updated.save(source)
    merge.install_fonts(outputs[0], installed)
    assert target.read_bytes() == source.read_bytes()
    target.write_bytes(b"different")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        merge.install_fonts(outputs[0], installed)
    result = CliRunner().invoke(
        merge.app,
        [
            "--sarasa",
            str(sarasa),
            "--lilex-dir",
            str(latin_dir),
            "--nerd-font",
            str(nerd_font),
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
    assert (
        output / "nerd-fonts/SymbolsNerdFontMono-Regular.ttf"
    ).read_bytes() == b"font fixture"
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


def test_ci_skips_unrelated_or_published_inputs(tmp_path, monkeypatch):
    import subprocess
    from urllib.error import HTTPError

    repository = sources.DEFAULT_MANIFEST.parent
    fingerprint = sources.input_id(repository)
    payload = {
        "draft": False,
        "body": f"<!-- terminal-font-inputs: {fingerprint} -->",
        "assets": [{"name": "terminal-fonts.zip", "state": "uploaded"}],
    }
    assert sources.release_is_current(payload, fingerprint)
    assert not sources.release_is_current(payload, "different")
    assert not sources.release_is_current({**payload, "assets": []}, fingerprint)
    assert not sources.release_is_current({**payload, "draft": True}, fingerprint)
    output = tmp_path / "outputs"
    monkeypatch.setattr(sources, "release", lambda font: payload)
    result = CliRunner().invoke(sources.app, ["plan", "--github-output", str(output)])
    assert result.exit_code == 0, result.exception
    assert "build_required=false" in output.read_text()
    monkeypatch.setattr(
        sources,
        "release",
        lambda font: (_ for _ in ()).throw(HTTPError("url", 404, "missing", {}, None)),
    )
    result = CliRunner().invoke(sources.app, ["plan", "--github-output", str(output)])
    assert result.exit_code == 0
    assert output.read_text().endswith(f"build_required=true\ninput_id={fingerprint}\n")
    monkeypatch.setattr(
        sources,
        "release",
        lambda font: (_ for _ in ()).throw(
            HTTPError("url", 403, "rate limited", {}, None)
        ),
    )
    assert CliRunner().invoke(sources.app, ["plan"]).exit_code != 0
    monkeypatch.setattr(
        sources.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "README.md\n", ""),
    )
    result = CliRunner().invoke(
        sources.app, ["plan", "--base", "a" * 40, "--head", "b" * 40]
    )
    assert result.exit_code == 0 and "跳过构建" in result.output
    monkeypatch.setattr(
        sources.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "scripts/merge_terminal_fonts.py\n", ""
        ),
    )
    assert (
        CliRunner()
        .invoke(sources.app, ["plan", "--base", "a" * 40, "--head", "b" * 40])
        .exit_code
        != 0
    )
    assert CliRunner().invoke(sources.app, ["plan", "--base", "a" * 40]).exit_code != 0


def test_ci_input_fingerprint_changes_with_scripts(tmp_path):
    original = sources.input_id(sources.DEFAULT_MANIFEST.parent)
    for path in sources.build_inputs(sources.DEFAULT_MANIFEST.parent):
        relative = path.relative_to(sources.DEFAULT_MANIFEST.parent)
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    assert sources.input_id(tmp_path) == original
    (tmp_path / "scripts/merge_terminal_fonts.py").write_bytes(b"changed converter")
    assert sources.input_id(tmp_path) != original


def test_release_notes_use_bundled_source_versions(tmp_path):
    import zipfile

    manifest = sources.DEFAULT_MANIFEST.read_text().replace(
        'tag = "2.700"', 'tag = "2.777"'
    )
    bundle = tmp_path / "terminal-fonts.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("terminal-fonts.toml", manifest)
        archive.writestr(
            "build-report.json",
            json.dumps({"family": "DCjanus Mono SC", "build_id": "fixture-build"}),
        )
    output = tmp_path / "release.md"
    result = CliRunner().invoke(
        sources.app,
        [
            "notes",
            "--bundle",
            str(bundle),
            "--commit",
            "a" * 40,
            "--fingerprint",
            "b" * 64,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.exception
    content = output.read_text()
    assert "## 上游来源" in content
    assert "releases/tag/2.777" in content and "2.700" not in content
    assert "releases/tag/v1.0.42" in content
    assert "releases/tag/v3.5.1" in content
    assert 'font-family = "DCjanus Mono SC"' in content
    assert f"<!-- terminal-font-inputs: {'b' * 64} -->" in content
