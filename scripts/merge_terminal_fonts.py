#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "blake3>=1.0.11",
#     "fonttools>=4.66.1",
#     "rich>=15.0.0",
#     "typer>=0.27.3",
#     "uharfbuzz>=0.56.3",
# ]
# ///


from __future__ import annotations

import copy
import json
import re
import shutil
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Annotated

import typer
import uharfbuzz as hb
from blake3 import blake3
from fontTools import subset
from fontTools.merge import Merger
from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen, ControlBoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from fontTools.ttLib.scaleUpem import scale_upem
from rich.console import Console

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
console = Console()
STYLES = {
    "Regular": "Sarasa-Term-SC-Regular",
    "Bold": "Sarasa-Term-SC-Bold",
    "Italic": "Sarasa-Term-SC-Italic",
    "BoldItalic": "Sarasa-Term-SC-Bold-Italic",
}
LATIN_RANGES = (
    (0x20, 0xFF),
    (0x100, 0x24F),
    (0x1E00, 0x1EFF),
    (0x2000, 0x206F),
    (0x20A0, 0x20CF),
)
SHAPING_SAMPLES = (
    "ABC abc MWmw 0123456789 0xFF",
    "-> => != == === <= >=",
    "ffi fl",
    "a\u0301",
)


def digest(path: Path) -> str:
    """流式计算内容标识。"""
    hasher = blake3()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def install_fonts(output_dir: Path, install_dir: Path) -> None:
    """覆盖安装同家族、同样式字体，拒绝无关文件，并逐文件原子替换。"""
    fonts = sorted(output_dir.glob("*.ttf"))
    for source in fonts:
        target = install_dir / source.name
        if target.exists() and digest(target) != digest(source):
            try:
                with TTFont(source) as new, TTFont(target) as old:
                    if any(
                        new["name"].getDebugName(key) != old["name"].getDebugName(key)
                        for key in (1, 2)
                    ):
                        raise ValueError("家族或样式不同")
            except Exception as error:
                raise ValueError(f"拒绝覆盖无关或无效字体：{target.name}") from error
    install_dir.mkdir(parents=True, exist_ok=True)
    for source in fonts:
        with NamedTemporaryFile(dir=install_dir, suffix=".tmp", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            shutil.copyfile(source, temporary)
            if digest(temporary) != digest(source):
                raise ValueError(f"安装前校验失败：{source.name}")
            temporary.replace(install_dir / source.name)
        finally:
            temporary.unlink(missing_ok=True)


def subset_font(
    font: TTFont, unicodes: set[int], *, drop_features: set[str] | None = None
) -> None:
    """裁剪字符，同时保留连字及其引用字形。"""
    options = subset.Options()
    options.layout_features = ["*"]
    if drop_features:
        options.layout_features = sorted(
            {
                feature.FeatureTag
                for tag in ("GSUB", "GPOS")
                if tag in font
                for feature in font[tag].table.FeatureList.FeatureRecord
            }
            - drop_features
        )
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    worker = subset.Subsetter(options=options)
    worker.populate(unicodes=unicodes)
    worker.subset(font)


def scale_layout(value: object, factor: float, seen: set[int]) -> None:
    """同步缩放静态 OpenType 的水平定位数据。"""
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, (list, tuple)):
        for item in value:
            scale_layout(item, factor, seen)
    elif hasattr(value, "__dict__"):
        for key, item in vars(value).items():
            if (
                key in {"XPlacement", "XAdvance", "XCoordinate"}
                and item is not None
                or key == "Coordinate"
                and type(value).__name__ == "CaretValue"
            ):
                setattr(value, key, otRound(item * factor))
            elif key in {"XPlaDevice", "XAdvDevice", "XDeviceTable", "DeviceTable"}:
                # 重绘轮廓后丢弃原来的像素级微调。
                setattr(value, key, None)
            else:
                scale_layout(item, factor, seen)


def scale_horizontal(font: TTFont, factor: float) -> None:
    """水平缩放轮廓、占宽及布局，保持高度和基线。"""
    if "glyf" not in font or "fvar" in font:
        raise ValueError("仅支持静态 TrueType 字体")
    glyph_set = font.getGlyphSet()
    replacements = {}
    for name in font.getGlyphOrder():
        recording = DecomposingRecordingPen(glyph_set)
        glyph_set[name].draw(recording)
        pen = TTGlyphPen(None)
        recording.replay(TransformPen(pen, (factor, 0, 0, 1, 0, 0)))
        replacements[name] = pen.glyph()
    font["glyf"].glyphs = replacements
    font["hmtx"].metrics = {
        name: (otRound(width * factor), otRound(lsb * factor))
        for name, (width, lsb) in font["hmtx"].metrics.items()
    }
    for tag in ("GPOS", "GDEF"):
        if tag in font:
            scale_layout(font[tag].table, factor, set())
    if "kern" in font:
        for table in font["kern"].kernTables:
            table.kernTable = {
                pair: otRound(v * factor) for pair, v in table.kernTable.items()
            }
    font["hhea"].caretSlopeRun = otRound(font["hhea"].caretSlopeRun * factor)
    font["OS/2"].xAvgCharWidth = otRound(font["OS/2"].xAvgCharWidth * factor)
    for tag in ("fpgm", "prep", "cvt ", "hdmx", "LTSH", "VDMX"):
        if tag in font:
            del font[tag]


def ligature_glyphs(font: TTFont) -> set[str]:
    """收集编程连字的替代字形与符号，保持它们的连接几何。"""
    table = font["GSUB"].table
    indexes = set()
    for feature in table.FeatureList.FeatureRecord:
        if feature.FeatureTag in {"calt", "liga", "dlig", "rlig"}:
            indexes.update(feature.Feature.LookupListIndex)
    glyph_names = set(font.getGlyphOrder())
    names: set[str] = set()
    seen: set[int] = set()

    def walk(value: object) -> None:
        """遍历上下文查找及间接引用。"""
        if isinstance(value, str):
            if value in glyph_names:
                names.add(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif hasattr(value, "__dict__") and id(value) not in seen:
            seen.add(id(value))
            if hasattr(value, "LookupListIndex"):
                indexes.add(value.LookupListIndex)
            for item in vars(value).values():
                walk(item)

    processed: set[int] = set()
    while indexes - processed:
        index = next(iter(indexes - processed))
        processed.add(index)
        walk(table.LookupList.Lookup[index])
    # 普通字母数字独立排布；专用替代字形和操作符仍用统一变换。
    names -= {name for cp, name in font.getBestCmap().items() if chr(cp).isalnum()}
    return names


def fit_sidebearings(font: TTFont, factor: float) -> dict[str, int]:
    """优先减少侧边距，过宽才压缩；编程连字保留统一缩放。"""
    if "glyf" not in font or "fvar" in font:
        raise ValueError("仅支持静态 TrueType 字体")
    if font["GDEF"].table.LigCaretList is not None:
        raise ValueError("暂不支持带连字光标定位的来源字体")
    protected = ligature_glyphs(font)
    glyphs = font.getGlyphSet()
    replacements = {}
    transforms = {}
    counts = {"unchanged_scale": 0, "fit_scaled": 0, "ligature_uniform": 0}
    gpos = copy.deepcopy(font["GPOS"])
    old_metrics = dict(font["hmtx"].metrics)
    for name in font.getGlyphOrder():
        bounds = BoundsPen(glyphs)
        glyphs[name].draw(bounds)
        old_width, _ = old_metrics[name]
        new_width = otRound(old_width * factor)
        if name in protected:
            sx, dx = factor, 0
            counts["ligature_uniform"] += 1
        elif bounds.bounds and old_width > 0:
            x_min, _, x_max, _ = bounds.bounds
            # 每边预留目标占宽的 2%，保留一点字符间隔。
            usable_width = new_width * 0.96
            sx = min(1.0, usable_width / (x_max - x_min)) if x_max > x_min else 1.0
            dx = (new_width - (x_min + x_max) * sx) / 2
            counts["unchanged_scale" if sx == 1 else "fit_scaled"] += 1
        else:
            sx, dx = 1.0, 0.0
        recording = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(recording)
        pen = TTGlyphPen(None)
        recording.replay(TransformPen(pen, (sx, 0, 0, 1, dx, 0)))
        replacements[name] = pen.glyph()
        transforms[name] = (sx, dx)
    # 先处理公共表和 hinting，再覆盖为各字形的独立轮廓与侧边距。
    scale_horizontal(font, factor)
    font["glyf"].glyphs = replacements
    font["hmtx"].metrics = {
        name: (
            otRound(width * factor),
            otRound(lsb * transforms[name][0] + transforms[name][1]),
        )
        for name, (width, lsb) in old_metrics.items()
    }

    def anchor(value: object, name: str) -> None:
        """同步字形对应的标记锚点。"""
        if value is not None:
            sx, dx = transforms[name]
            value.XCoordinate = otRound(value.XCoordinate * sx + dx)
            # 重绘后的点索引和像素微调不可沿用。
            value.Format = 1

    for lookup in gpos.table.LookupList.Lookup:
        if lookup.LookupType != 4:
            raise ValueError("仅支持当前 Lilex 的 MarkBase GPOS 表")
        for subtable in lookup.SubTable:
            for name, record in zip(
                subtable.MarkCoverage.glyphs, subtable.MarkArray.MarkRecord, strict=True
            ):
                anchor(record.MarkAnchor, name)
            for name, record in zip(
                subtable.BaseCoverage.glyphs, subtable.BaseArray.BaseRecord, strict=True
            ):
                for value in record.BaseAnchor:
                    anchor(value, name)
    font["GPOS"] = gpos
    return counts


def shape(path: Path, text: str, features: dict[str, bool]) -> list[tuple]:
    """读取实际字体文件并运行连字及定位。"""
    font = hb.Font(hb.Face(path.read_bytes()))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, features)
    return [
        (i.codepoint, i.cluster, p.x_advance, p.y_advance, p.x_offset, p.y_offset)
        for i, p in zip(buf.glyph_infos, buf.glyph_positions, strict=True)
    ]


def fit_icons(font: TTFont, width: int, ascent: int, descent: int) -> None:
    """将 Symbols Mono 图标等比放入单格，保持轮廓比例并居中。"""
    if "glyf" not in font or "fvar" in font:
        raise ValueError("图标来源必须是静态 TrueType 字体")
    glyphs = font.getGlyphSet()
    replacements, metrics = {}, {}
    for name in font.getGlyphOrder():
        # TTF 的字形边界按控制点计算；仅按曲线极值适配可能在取整后越界。
        bounds = ControlBoundsPen(glyphs)
        glyphs[name].draw(bounds)
        recording = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(recording)
        pen = TTGlyphPen(None)
        advance = font["hmtx"][name][0]
        scale = width / advance if advance > 0 else 1.0
        dx = dy = 0.0
        if bounds.bounds:
            left, bottom, right, top = bounds.bounds
            if right > left:
                scale = min(scale, width / (right - left))
            if top > bottom:
                scale = min(scale, (ascent - descent) / (top - bottom))
            dx = (width - (left + right) * scale) / 2
            dy = (ascent + descent - (bottom + top) * scale) / 2
        recording.replay(TransformPen(pen, (scale, 0, 0, scale, dx, dy)))
        glyph = pen.glyph()
        replacements[name] = glyph
        metrics[name] = (
            width,
            otRound(bounds.bounds[0] * scale + dx) if bounds.bounds else 0,
        )
    font["glyf"].glyphs = replacements
    font["hmtx"].metrics = metrics
    # 图标无需文字布局及原像素微调，避免其表参与西文布局合并。
    for tag in (
        "GSUB",
        "GPOS",
        "GDEF",
        "kern",
        "fpgm",
        "prep",
        "cvt ",
        "hdmx",
        "LTSH",
        "VDMX",
        "PfEd",
    ):
        if tag in font:
            del font[tag]


def verify_icons(
    output: Path, codepoints: set[int], added: set[int], width: int
) -> None:
    """确认完整图标覆盖及新图标的单格占宽、轮廓边界。"""
    with TTFont(output) as font:
        cmap = font.getBestCmap()
        if missing := codepoints - set(cmap):
            raise ValueError(f"缺少 Nerd Fonts 字符：{sorted(missing)}")
        for cp in added:
            name = cmap[cp]
            if font["hmtx"][name][0] != width:
                raise ValueError(f"图标占宽异常：U+{cp:04X}")
            glyph = font["glyf"][name]
            if glyph.numberOfContours and not (
                0 <= glyph.xMin <= glyph.xMax <= width
                and font["hhea"].descent
                <= glyph.yMin
                <= glyph.yMax
                <= font["hhea"].ascent
            ):
                raise ValueError(f"图标越出单格：U+{cp:04X}")


def verify(output: Path, latin: Path, target_width: int) -> None:
    """检查双格中文、单格西文和合并后的布局结果。"""
    with TTFont(output) as font, TTFont(latin) as source:
        cmap = font.getBestCmap()
        for char in " ABCabc0123":
            if font["hmtx"][cmap[ord(char)]][0] != target_width:
                raise ValueError(f"西文占宽异常：{char!r}")
        for char in "中文测试":
            if font["hmtx"][cmap[ord(char)]][0] != target_width * 2:
                raise ValueError(f"中文占宽异常：{char}")
        ligatures_changed = False
        for text in SHAPING_SAMPLES:
            ligatures_changed |= shape(
                latin, text, {"calt": True, "liga": True}
            ) != shape(latin, text, {"calt": False, "liga": False})
            for enabled in (True, False):
                features = {"calt": enabled, "liga": enabled, "dlig": enabled}
                before = shape(latin, text, features)
                after = shape(output, text, features)
                # 合并会重新分配 glyph ID；比较真实轮廓、字符归属和定位。
                if [r[1:] for r in before] != [r[1:] for r in after]:
                    raise ValueError(f"合并改变了西文布局：{text!r}")
                for left, right in zip(before, after, strict=True):
                    a = source["glyf"][source.getGlyphName(left[0])]
                    b = font["glyf"][font.getGlyphName(right[0])]
                    if a.compile(source["glyf"]) != b.compile(font["glyf"]):
                        raise ValueError(f"合并改变了西文轮廓：{text!r}")
        if not ligatures_changed:
            raise ValueError("来源西文未在测试样例中触发连字，请检查来源字体")


def rename(
    font: TTFont,
    family: str,
    style: str,
    notices: dict[int, str],
    weight: int,
    build_id: str,
) -> None:
    """创建独立家族并保留三份来源声明。"""
    display_style = "Bold Italic" if style == "BoldItalic" else style
    ps_family = re.sub(r"[^A-Za-z0-9]", "", family) + build_id
    values = {
        1: family,
        2: display_style,
        3: f"{ps_family}-{style}",
        4: f"{family} {display_style}",
        5: f"Version 1.000; build {build_id}",
        6: f"{ps_family}-{style}",
        16: family,
        17: display_style,
        **notices,
    }
    font["name"].names = []
    for name_id, value in values.items():
        font["name"].setName(value, name_id, 3, 1, 0x409)
    bold = "Bold" in style
    italic = "Italic" in style
    font["OS/2"].usWeightClass = weight
    font["OS/2"].fsSelection = (
        (1 if italic else 0)
        | (32 if bold else 0)
        | (64 if not bold and not italic else 0)
    )
    font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)


@app.command()
def main(
    sarasa: Annotated[
        Path,
        typer.Option(
            exists=True,
            dir_okay=False,
            readable=True,
            help="更纱 SuperTTC；按 PostScript 名称查找 Term SC 四个样式。",
        ),
    ],
    lilex_dir: Annotated[
        Path,
        typer.Option(
            exists=True,
            file_okay=False,
            readable=True,
            help="含 Lilex-{Regular,Bold,Italic,BoldItalic}.ttf 的目录。",
        ),
    ],
    nerd_font: Annotated[
        Path,
        typer.Option(
            exists=True,
            dir_okay=False,
            readable=True,
            help="完整 SymbolsNerdFontMono-Regular.ttf 图标字体。",
        ),
    ],
    output_dir: Annotated[
        Path, typer.Option(file_okay=False, help="输出目录；必须不存在，避免覆盖。")
    ],
    family: Annotated[
        str, typer.Option(help="固定家族名（含 ASCII 字母）；更新无需修改 Ghostty。")
    ] = "DCjanus Mono SC",
    install_dir: Annotated[
        Path | None,
        typer.Option(
            file_okay=False, help="可选安装目录；覆盖同家族同样式文件，默认仅生成。"
        ),
    ] = None,
) -> None:
    """合并 Lilex、更纱与完整 Nerd Fonts 图标集，保留中文及编程连字。

    生成四个静态 TTF、构建报告、许可证及 Ghostty 配置片段。
    家族名和文件名固定；内部标识随构建变化，不修改 Ghostty 配置。
    """
    if output_dir.exists():
        raise typer.BadParameter(
            "输出目录已存在，请换一个目录", param_hint="--output-dir"
        )
    if not re.search(r"[A-Za-z]", family) or len(family) > 40:
        raise typer.BadParameter(
            "家族名需包含 ASCII 字母，且不超过 40 字符", param_hint="--family"
        )
    paths = {style: lilex_dir / f"Lilex-{style}.ttf" for style in STYLES}
    for path in paths.values():
        if not path.is_file():
            raise typer.BadParameter(f"缺少 {path.name}", param_hint="--lilex-dir")
    provenance = {
        "sources": [
            {"file": path.name, "blake3": digest(path)}
            for path in [sarasa, *paths.values(), nerd_font]
        ],
        "converter": digest(Path(__file__)),
        "dependencies": {name: version(name) for name in ("fonttools", "uharfbuzz")},
        "family_base": family,
    }
    build_id = blake3(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:12]
    collection = TTCollection(sarasa, lazy=True)
    faces = {}
    for face in collection.fonts:
        ps_name = face["name"].getDebugName(6)
        if ps_name in STYLES.values():
            if ps_name in faces:
                raise ValueError(f"重复的来源样式：{ps_name}")
            faces[ps_name] = face
    if set(faces) != set(STYLES.values()):
        raise typer.BadParameter(
            "TTC 不包含完整 Sarasa Term SC 四个样式", param_hint="--sarasa"
        )
    reports = []
    with TemporaryDirectory(prefix="terminal-font-merge-") as temp:
        staging = Path(temp)
        for style, ps_name in STYLES.items():
            console.print(f"处理 {style}…")
            cjk = faces[ps_name]
            latin = TTFont(paths[style])
            icons = TTFont(nerd_font)
            if icons["name"].getDebugName(1) != "Symbols Nerd Font Mono":
                raise ValueError("图标来源须为 Symbols Nerd Font Mono")
            icon_codepoints = set(icons.getBestCmap()) - {0, 0x20, 0xA0}
            weight = latin["OS/2"].usWeightClass
            if cjk["head"].unitsPerEm != latin["head"].unitsPerEm:
                raise ValueError("来源字体 UPEM 不同，当前不支持")
            width = cjk["hmtx"][cjk.getBestCmap()[ord("A")]][0]
            original_width = latin["hmtx"][latin.getBestCmap()[ord("A")]][0]
            factor = width / original_width
            selected = {
                cp
                for cp in latin.getBestCmap()
                if any(start <= cp <= end for start, end in LATIN_RANGES)
            }
            existing = set(cjk.getBestCmap()) | selected
            added_icons = icon_codepoints - existing
            if not added_icons:
                raise ValueError("图标来源没有可加入的图标")
            notices = {
                name_id: "\n\n".join(
                    filter(
                        None,
                        (
                            cjk["name"].getDebugName(name_id),
                            latin["name"].getDebugName(name_id),
                            icons["name"].getDebugName(name_id),
                        ),
                    )
                )
                for name_id in (0, 13, 14)
            }
            metrics = copy.deepcopy(cjk["hhea"])
            os2 = copy.deepcopy(cjk["OS/2"])
            # WWID 的双格替代字形会使完整 Nerd Fonts 超出 TTF 字形上限。
            # 保留所有字符和默认占宽，仅移除可选的双格字宽替换。
            subset_font(cjk, set(cjk.getBestCmap()) - selected, drop_features={"WWID"})
            subset_font(latin, selected)
            fit_counts = fit_sidebearings(latin, factor)
            subset_font(icons, added_icons)
            scale_upem(icons, cjk["head"].unitsPerEm)
            fit_icons(icons, width, metrics.ascent, metrics.descent)
            # Lilex 直立样式有竖排表，斜体没有。终端不使用竖排，统一移除，
            # 避免 Merger 无法合并缺失一侧的 vhea/vmtx。
            for font in (cjk, latin, icons):
                for tag in ("vhea", "vmtx", "VORG"):
                    if tag in font:
                        del font[tag]
            cjk_path, latin_path = staging / "cjk.ttf", staging / "latin.ttf"
            cjk.recalcTimestamp = latin.recalcTimestamp = False
            cjk.save(cjk_path)
            latin.save(latin_path)
            icons_path = staging / "icons.ttf"
            icons.recalcTimestamp = False
            icons.save(icons_path)
            merged = Merger().merge([str(cjk_path), str(latin_path), str(icons_path)])
            if len(merged.getGlyphOrder()) > 65535:
                raise ValueError(
                    f"合并后有 {len(merged.getGlyphOrder())} 个字形，超出 TTF 的 65535 上限"
                )
            # 保留更纱的行高；防止 Merger 自动选用 Lilex 的更大行高。
            for attr in ("ascent", "descent", "lineGap"):
                setattr(merged["hhea"], attr, getattr(metrics, attr))
            for attr in (
                "sTypoAscender",
                "sTypoDescender",
                "sTypoLineGap",
                "usWinAscent",
                "usWinDescent",
            ):
                setattr(merged["OS/2"], attr, getattr(os2, attr))
            merged["post"].italicAngle = latin["post"].italicAngle
            merged.recalcTimestamp = False
            merged["head"].created = cjk["head"].created
            merged["head"].modified = max(cjk["head"].modified, latin["head"].modified)
            merged["post"].isFixedPitch = 1
            rename(merged, family, style, notices, weight, build_id)
            filename = f"{re.sub(r'[^A-Za-z0-9]', '', family)}-{style}.ttf"
            output = staging / filename
            merged.save(output)
            verify(output, latin_path, width)
            verify_icons(output, icon_codepoints, added_icons, width)
            reports.append(
                {
                    "style": style,
                    "file": filename,
                    "latin_source": paths[style].name,
                    "latin_weight": weight,
                    "advance_scale": factor,
                    "fit_mode": "tight",
                    "fit_counts": fit_counts,
                    "latin_width": width,
                    "cjk_width": width * 2,
                    "icons_source": nerd_font.name,
                    "cjk_features_removed": ["WWID"],
                    "icons_covered": len(icon_codepoints),
                    "icons_added": len(added_icons),
                    "icons_preserved": [
                        f"U+{cp:04X}" for cp in sorted(icon_codepoints & existing)
                    ],
                    "glyphs": merged["maxp"].numGlyphs,
                    "blake3": digest(output),
                    "validation": "widths, outlines, HarfBuzz shaping and full icon coverage passed",
                }
            )
            merged.close()
            latin.close()
            icons.close()
        output_dir.mkdir(parents=True)
        for report in reports:
            (output_dir / report["file"]).write_bytes(
                (staging / report["file"]).read_bytes()
            )
        (output_dir / "build-report.json").write_text(
            json.dumps(
                {
                    "family": family,
                    "build_id": build_id,
                    "faces": reports,
                    **provenance,
                    "notes": "收紧西文侧边距；保留中文与行高；移除西文 hinting 和更纱 WWID 可选字宽替换；完整 Nerd Fonts 图标等比适配单格。",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    licenses = Path(__file__).resolve().parents[1] / "licenses" / "terminal-fonts"
    for name in ("Lilex.txt", "Sarasa-Gothic.txt", "Nerd-Fonts.txt"):
        shutil.copyfile(licenses / name, output_dir / name)
    (output_dir / "ghostty.font.conf").write_text(
        f'# 移除旧 font-codepoint-map 后使用。\nfont-family = ""\nfont-family = "{family}"\n',
        encoding="utf-8",
    )
    collection.close()
    if install_dir is not None:
        install_fonts(output_dir, install_dir)
    console.print(f"已输出并验证：{output_dir}")


if __name__ == "__main__":
    app()
