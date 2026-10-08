# DC Mono SC 终端字体

将 Lilex 的西文字形与更纱 Term SC 的中文、框线合并为单一字体，包含 Regular、Bold、Italic、Bold Italic 四个样式。Ghostty 无需 `font-codepoint-map`，常规、粗体及斜体直接选择同一家族中的对应样式。

## 下载与安装

从 [固定字体 release](https://github.com/DCjanus/prompts/releases/tag/terminal-fonts-latest) 下载 `terminal-fonts.zip`。解压后将四个 `.ttf` 安装到 macOS 的 `~/Library/Fonts/`；其他系统按其字体安装方式处理。压缩包还包含来源清单、构建报告、两份 OFL 许可证和 `ghostty.font.conf`。

备份 Ghostty 配置，移除现有 `font-family`、`font-family-bold`、`font-family-italic`、`font-family-bold-italic` 和所有 `font-codepoint-map`，再加入包内 `ghostty.font.conf` 的内容。保留主题等其他设置。重载配置后新建窗口；未发现新字体时退出并重新启动 Ghostty。

家族名固定为 `DC Mono SC`，文件名也固定。更新时覆盖四个 `.ttf`，退出并重新启动 Ghostty；无需修改配置。构建指纹保留在内部 PostScript 名称、唯一标识与报告中，让新字体具有不同的内部身份；正在运行的 Ghostty 仍可能持有旧字体，因此需要重启。不要删除来源字体或其他家族。

## 本地构建

需要 [uv](https://github.com/astral-sh/uv)，脚本自动管理 Python 与依赖。仓库不存储字体二进制文件。

```sh
./scripts/terminal_font_sources.py check
./scripts/terminal_font_sources.py fetch --output-dir /tmp/font-sources
./scripts/merge_terminal_fonts.py \
  --sarasa /tmp/font-sources/sarasa/Sarasa-SuperTTC.ttc \
  --lilex-dir /tmp/font-sources/lilex \
  --output-dir /tmp/terminal-fonts \
  --install-dir "$HOME/Library/Fonts"
```

来源和产物目录必须不存在。`--install-dir` 可省略；指定后覆盖同家族、同样式的文件，拒绝覆盖无关或无效字体；先校验再逐文件原子替换。不自动修改 Ghostty。`--family` 可指定独立家族基础名，默认 `DC Mono SC`，家族与文件名保持固定，内部标识包含由来源、转换脚本和布局库版本计算出的 BLAKE3 构建指纹。

## 上游更新与发布

[terminal-fonts.toml](../terminal-fonts.toml) 固定已验收的来源 tag、资产名和 GitHub 提供的 SHA-256 摘要；`observed_latest` 单独记录已检查过的上游 latest 发布 ID。当前 Lilex 构建采用已验收的 `2.700`；上游较晚发布的 `2.630` 虽然版本号更低，代码实际更新，因此不根据版本号大小判断更新。

每个 PR 都检查上游 latest 发布及固定版本附件摘要。新发布、资产被替换或查询失败都会让 CI 失败，不自动采用未经验收的字体。没有定时检查。

介入更新时：查看上游发布说明，修改构建 tag、资产名、摘要和成员路径，重新构建并验收四样式、编程连字、中文对齐与字符画；确认后更新 `observed_latest`。若有意继续采用旧版本，说明原因后仅更新检查基线。许可证随来源更新一起核对。

CI 下载并验证来源、生成四样式字体并验证布局。PR 仅提供保留三天的构建 artifact；默认分支成功构建后覆盖固定 `terminal-fonts-latest` release 的 `terminal-fonts.zip`，不创建版本号 release，也不累积字体附件。手动触发仅在默认分支发布。发布需仓库允许 `GITHUB_TOKEN` 写入 contents，并允许可更新的 release；不要为该滚动 release 启用不可变发布。

## 转换与验证

- 替换 Lilex 实际包含的 U+0020–00FF、U+0100–024F、U+1E00–1EFF、U+2000–206F、U+20A0–20CF 字符，其余来自更纱。
- 由来源占宽计算终端网格。优先收紧西文侧边距并居中，过宽字形缩到单格的 96%，高度保持不变；中文、框线、块字符和更纱行高保持原样。
- 编程连字符号和专用替代字形采用统一水平缩放，以保留连接几何。保留 GSUB，同步 MarkBase 锚点，移除重绘后的西文 hinting 和终端不用的竖排表。
- 输出前检查西文单格、中文双格，以及连字开关下的轮廓、字符归属和 HarfBuzz 定位。保留两套来源的版权信息，并附完整 OFL 许可证。产物使用独立名称。

这是针对这两套静态 TrueType 字体的转换器，不是任意字体的通用合并器；新的 GPOS 结构或连字插入光标定位表会被拒绝。自动检查无法替代小字号、斜体边缘、粗体和框线的视觉验收。

用 ANSI 直接检查 Ghostty 的样式：

```sh
printf 'Regular: ABC abc 0123 中文测试 -> !=\n\033[1mBold:    ABC abc 0123 中文测试 -> !=\033[0m\n\033[3mItalic:  ABC abc 0123 中文测试 -> !=\033[0m\n\033[1;3mBoth:    ABC abc 0123 中文测试 -> !=\033[0m\n'
```

## 来源与许可

[Lilex](https://github.com/mishamyrt/Lilex) 和 [Sarasa Gothic](https://github.com/be5invis/Sarasa-Gothic) 均按 SIL Open Font License 1.1 使用。完整文本分别保存在 [Lilex.txt](../licenses/terminal-fonts/Lilex.txt) 和 [Sarasa-Gothic.txt](../licenses/terminal-fonts/Sarasa-Gothic.txt)，并随每份构建产物分发。
