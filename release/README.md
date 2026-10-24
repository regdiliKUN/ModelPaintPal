# 发行包 · ModelPaintPal

本目录存放 **ModelPaintPal** 的 Windows x64 可运行包体（由桌面快捷方式实际指向的安装/发布目录整理而来）。

| 项目 | 内容 |
| --- | --- |
| 版本 | `2026.10.24` |
| 平台 | Windows x64 |
| 包体路径 | `release/2026.10.24/ModelPaintPal-2026.10.24-win-x64/` |
| 文件数 | 287 |
| 体积 | 约 135.4 MB |

## 运行方式

双击 `ModelPaintPal.exe`

## 校验完整性

```bash
cd release
sha256sum -c SHA256SUMS.txt
```

Windows PowerShell：

```powershell
Get-Content release\SHA256SUMS.txt | ForEach-Object {
  $h, $p = $_ -split '  ', 2
  if ((Get-FileHash $p -Algorithm SHA256).Hash -ne $h.ToUpper()) { "MISMATCH $p" }
}
```

## 关于 ModelPaintPal

手办涂装配色助手（便携版）。

## 未纳入的内容

本地用户数据 `userdata/`、`userdata_backup_20261022/` 未纳入。

以上目录属于开发环境、运行期缓存或大体积模型权重，不影响程序本体运行。
