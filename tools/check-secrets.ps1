#requires -Version 7.0
<#
.SYNOPSIS
    发布前脱敏检查 —— 扫描目录里是否残留 API Key / 密钥 / 本机用户名。

.DESCRIPTION
    用于把技术文档、示例代码公开发布（博客 / GitHub / 公众号）之前的最后一道闸。
    命中即退出码 1，可直接挂到 CI 或 git pre-commit。

.PARAMETER Path
    要扫描的目录，默认是本脚本所在目录的上一级（即项目根）。

.PARAMETER Ignore
    忽略的文件名通配符，默认排除 node_modules、.git、__pycache__ 等。

.EXAMPLE
    pwsh -File tools/check-secrets.ps1
    pwsh -File tools/check-secrets.ps1 -Path D:\blog\qianfan
#>
param(
    [string]$Path = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# 真实密钥的特征。占位符（xxx / fake / <你的...>）不算命中。
$rules = @(
    @{ Name = '百度千帆 API Key'; Regex = 'bce-v3/ALTAK-(?!x{3,}|fake)[A-Za-z0-9]{8,}'; Why = '完整 API Key' }
    @{ Name = '千帆 secret 段';    Regex = '(?<=ALTAK-[A-Za-z0-9]{6,}/)[0-9a-f]{32,}';    Why = 'Key 的 64 位 secret' }
    @{ Name = 'OpenAI 风格 Key';   Regex = '\bsk-[A-Za-z0-9]{20,}';                       Why = 'sk- 开头' }
    @{ Name = 'AWS Access Key';    Regex = '\bAKIA[0-9A-Z]{16}\b';                        Why = 'AWS' }
    @{ Name = '私钥块';            Regex = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'; Why = 'PEM' }
    @{ Name = '本机用户名路径';    Regex = 'C:\\Users\\(?!<|xxx|\$env)[A-Za-z0-9._-]{3,}\\'; Why = '会暴露你的 Windows 用户名' }
)

$skipDirs = @('node_modules', '.git', '__pycache__', '.venv', 'dist', 'build')
$skipGlobs = @('*.pyc', '.env', '*.jsonl', '*.exe', '*.zip')

$files = Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Where-Object {
    $rel = $_.FullName.Substring($Path.Length)
    $segments = $rel -split '[\\/]'
    if ($segments | Where-Object { $skipDirs -contains $_ }) { return $false }
    foreach ($g in $skipGlobs) {
        if ($_.Name -like $g) { return $false }
    }
    $_.Length -lt 5MB
}

Write-Host "扫描目录: $Path" -ForegroundColor Cyan
Write-Host "文件数  : $($files.Count)" -ForegroundColor Cyan
Write-Host ""

$findings = @()
foreach ($f in $files) {
    $text = Get-Content -LiteralPath $f.FullName -Raw -Encoding utf8
    if (-not $text) { continue }
    $lines = $text -split "`r?`n"
    for ($i = 0; $i -lt $lines.Count; $i++) {
        foreach ($rule in $rules) {
            $m = [regex]::Match($lines[$i], $rule.Regex)
            if ($m.Success) {
                $findings += [pscustomobject]@{
                    File = [System.IO.Path]::GetRelativePath($Path, $f.FullName)
                    Line = $i + 1
                    Rule = $rule.Name
                    Why  = $rule.Why
                    Snip = $m.Value.Substring(0, [Math]::Min(48, $m.Value.Length))
                }
            }
        }
    }
}

if ($findings.Count -eq 0) {
    Write-Host "✅ 未发现密钥或本机路径残留，可以发布。" -ForegroundColor Green
    exit 0
}

Write-Host "❌ 发现 $($findings.Count) 处可疑内容，禁止发布：" -ForegroundColor Red
Write-Host ""
$findings | Format-Table File, Line, Rule, Why, Snip -AutoSize | Out-String -Width 200 | Write-Host
Write-Host "处理方式：把命中内容替换成占位符（如 bce-v3/ALTAK-xxxxx/xxxxx），" -ForegroundColor Yellow
Write-Host "         或把 <用户名> 换成 <USER>，然后重新运行本脚本。" -ForegroundColor Yellow
exit 1
