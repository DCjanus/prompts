# DCjanus Mono SC 终端字体

将 Lilex 的西文字形、更纱 Term SC 的中文与框线，以及完整 Nerd Fonts Symbols Mono 图标集合并为单一字体，包含 Regular、Bold、Italic、Bold Italic 四个样式。Python、Git、文件夹等图标直接包含在字体文件中，不依赖终端的图标字体回退。Ghostty 无需 `font-codepoint-map`，常规、粗体及斜体直接选择同一家族中的对应样式。

## 下载与安装

从 [固定字体 release](https://github.com/DCjanus/prompts/releases/tag/terminal-fonts-latest) 下载 `terminal-fonts.zip`。解压后将四个 `.ttf` 安装到 macOS 的 `~/Library/Fonts/`；其他系统按其字体安装方式处理。压缩包还包含来源清单、构建报告、三份来源许可证和 `ghostty.font.conf`。

备份 Ghostty 配置，移除现有 `font-family`、`font-family-bold`、`font-family-italic`、`font-family-bold-italic` 和所有 `font-codepoint-map`，再加入包内 `ghostty.font.conf` 的内容。保留主题等其他设置。重载配置后新建窗口；未发现新字体时退出并重新启动 Ghostty。

家族名固定为 `DCjanus Mono SC`，文件名也固定。更新时覆盖四个 `.ttf`，退出并重新启动 Ghostty；无需修改配置。构建指纹保留在内部 PostScript 名称、唯一标识与报告中，让新字体具有不同的内部身份；正在运行的 Ghostty 仍可能持有旧字体，因此需要重启。不要删除来源字体或其他家族。

## 本地构建

需要 [uv](https://github.com/astral-sh/uv)，脚本自动管理 Python 与依赖。仓库不存储字体二进制文件。

```sh
./scripts/terminal_font_sources.py check
./scripts/terminal_font_sources.py fetch --output-dir /tmp/font-sources
./scripts/merge_terminal_fonts.py \
  --sarasa /tmp/font-sources/sarasa/Sarasa-SuperTTC.ttc \
  --lilex-dir /tmp/font-sources/lilex \
  --nerd-font /tmp/font-sources/nerd-fonts/SymbolsNerdFontMono-Regular.ttf \
  --output-dir /tmp/terminal-fonts \
  --install-dir "$HOME/Library/Fonts"
```

来源和产物目录必须不存在。`--install-dir` 可省略；指定后覆盖同家族、同样式的文件，拒绝覆盖无关或无效字体；先校验再逐文件原子替换。不自动修改 Ghostty。`--family` 可指定独立家族基础名，默认 `DCjanus Mono SC`，家族与文件名保持固定，内部标识包含由来源、转换脚本和布局库版本计算出的 BLAKE3 构建指纹。

**Breaking change（本地构建 CLI）**：`--nerd-font` 现在是必需参数。旧的构建命令需按上述示例加入该参数；来源清单必须同时包含 `sarasa`、`lilex`、`nerd-fonts`。已安装字体的家族名和终端配置无需迁移。构建只使用 fontTools，不需要 FontForge。

**Breaking change（可选排版特性）**：移除更纱的 `WWID` 特性及仅由它引用的替代字形，以便完整图标集不超出单个 TTF 的 65,535 字形上限。该特性原可将箭头、星号、带圈数字等符号切换为双格版本；移除后保留这些字符及其默认字形、默认占宽，但手动启用 `WWID` 不再生效。普通中文双格、西文单格和 Lilex 编程连字保留。

## 上游更新与发布

[terminal-fonts.toml](../terminal-fonts.toml) 固定已验收的来源 tag、资产名和 GitHub 提供的 SHA-256 摘要；`observed_latest` 单独记录已检查过的上游 latest 发布 ID。当前 Lilex 构建采用已验收的 `2.700`；上游较晚发布的 `2.630` 虽然版本号更低，代码实际更新，因此不根据版本号大小判断更新。

每个 PR 都检查上游 latest 发布及固定版本附件摘要。新发布、资产被替换或查询失败都会让 CI 失败，不自动采用未经验收的字体。没有定时检查。

介入更新时：查看上游发布说明，修改构建 tag、资产名、摘要和成员路径，重新构建并验收四样式、编程连字、中文对齐与字符画；确认后更新 `observed_latest`。若有意继续采用旧版本，说明原因后仅更新检查基线。许可证随来源更新一起核对。

每个 PR 的上游检查仅调用少量 GitHub API；使用自动提供的 `GITHUB_TOKEN`，无需配置个人 Token、variable 或 secret。PR 未修改来源清单、转换/下载脚本、许可证或字体 workflow 时，跳过字体构建。相关输入与现有 release 指纹一致时也跳过构建及发布。更新 PR 的新提交会取消同一个 PR 的旧构建。

确需构建时，CI 才下载并验证来源、生成四样式字体并验证布局。PR 仅提供保留三天的构建 artifact；默认分支成功构建后覆盖固定 `terminal-fonts-latest` release 的 `terminal-fonts.zip`，不创建版本号 release，也不累积字体附件。中文 release 正文从实际构建包读取上游版本，并链接对应发布、构建提交与安装说明。手动触发仅在默认分支发布。发布需仓库允许 `GITHUB_TOKEN` 写入 contents，并允许可更新的 release；不要为该滚动 release 启用不可变发布。

## 转换与验证

- 替换 Lilex 实际包含的 U+0020–00FF、U+0100–024F、U+1E00–1EFF、U+2000–206F、U+20A0–20CF 字符，其余来自更纱。
- 合并固定版本 Symbols Nerd Font Mono 的全部图标码位（排除 NUL、普通空格和不换行空格）。已有字符优先，保留更纱的 Powerline 等重叠符号；构建报告列出完整覆盖数量、新增数量及保留的码位。覆盖包括补充私用区，不只限于 U+E000–F8FF。
- 新增图标先统一 UPEM，再以来源占宽为基准等比缩放到西文单格；过宽或过高时进一步等比缩小，在单格和更纱行高内居中。四样式使用同一套直立图标，不人为加粗或倾斜；这是本项目的适配策略，不保证与官方 patcher 的视觉结果逐字形相同。
- 由来源占宽计算终端网格。优先收紧西文侧边距并居中，过宽字形缩到单格的 96%，高度保持不变；中文、框线、块字符和更纱行高保持原样。
- 编程连字符号和专用替代字形采用统一水平缩放，以保留连接几何。保留 GSUB，同步 MarkBase 锚点，移除重绘后的西文 hinting 和终端不用的竖排表。
- 更纱裁剪时仅排除 `WWID` 可选字宽特性，保留其他布局特性及所有字符码位；合并前检查字形数量上限，超限直接报错，不自动删减字符或图标。
- 输出前检查西文单格、中文双格，以及连字开关下的轮廓、字符归属和 HarfBuzz 定位；检查图标来源的全部码位覆盖、新增图标的单格占宽及轮廓边界。保留三套来源的版权信息，并附来源许可证。产物使用独立名称。

这是针对这些静态 TrueType 来源字体的转换器，不是任意字体的通用合并器；新的西文 GPOS 结构或连字插入光标定位表会被拒绝。自动检查无法替代小字号、斜体边缘、粗体、框线和图标的视觉验收。

用 ANSI 直接检查 Ghostty 的样式：

```sh
printf 'Regular: ABC abc 0123 中文测试 -> !=\n\033[1mBold:    ABC abc 0123 中文测试 -> !=\033[0m\n\033[3mItalic:  ABC abc 0123 中文测试 -> !=\033[0m\n\033[1;3mBoth:    ABC abc 0123 中文测试 -> !=\033[0m\n'
```

## 来源与许可

[Lilex](https://github.com/mishamyrt/Lilex) 和 [Sarasa Gothic](https://github.com/be5invis/Sarasa-Gothic) 均按 SIL Open Font License 1.1 使用。完整文本分别保存在 [Lilex.txt](../licenses/terminal-fonts/Lilex.txt) 和 [Sarasa-Gothic.txt](../licenses/terminal-fonts/Sarasa-Gothic.txt)，并随每份构建产物分发。

[Nerd Fonts](https://github.com/ryanoasis/nerd-fonts) 使用固定版本的 `NerdFontsSymbolsOnly.zip` 中的 `SymbolsNerdFontMono-Regular.ttf`。许可及图标来源声明保存在 [Nerd-Fonts.txt](../licenses/terminal-fonts/Nerd-Fonts.txt)，随构建产物分发。
