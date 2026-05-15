# gcloud ADC 安装与初始化

本 skill 默认用 `gcloud` 管理 OAuth/ADC，Python CLI 只读取 ADC 并调用 Google Sheets API。

## macOS 安装

优先使用 Homebrew：

```bash
brew install --cask gcloud-cli
gcloud --version
```

也可以使用 Google 官方安装包：

- [Install the Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install)

## 初始化 ADC

只操作已知 spreadsheet id 的读写、格式、table 和 batchUpdate 时，使用 Sheets scope：

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/spreadsheets
```

完成后检查：

```bash
cd skills/google-sheets-cli
./scripts/google_sheets.py --json auth doctor
./scripts/google_sheets.py --json auth scopes
```

## 什么时候加 Drive scope

只有需要创建、复制、搜索、移动 Google Drive 文件时才加 Drive scope。当前 CLI 第一版不创建 spreadsheet 文件，因此不默认要求 Drive 权限。

如果后续扩展到 Drive 文件操作，可重新登录：

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive.file
```

## 常见问题

`gcloud auth login` 和 `gcloud auth application-default login` 不是同一个用途：

- `gcloud auth login` 主要给 `gcloud` CLI 自己使用。
- `gcloud auth application-default login` 给应用程序和 Google 官方 client libraries 使用。

如果脚本报 scope 不足，通常需要重新运行 `gcloud auth application-default login` 并带上完整 scope。

如果脚本报无权限访问某个 spreadsheet，确认当前授权账号能在浏览器里打开该 spreadsheet，或者让拥有者分享访问权限给该账号。
