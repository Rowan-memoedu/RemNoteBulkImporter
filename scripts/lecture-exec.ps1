param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Output,
    [string]$Title,
    [ValidateSet('questions','teaching')][string]$SourceRole,
    [string]$Model = 'gpt-6-sol'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$outputPath = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$attempt = Join-Path $outputPath ('executions/'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
New-Item -ItemType Directory -Path $attempt -Force | Out-Null
$workflowLog = Join-Path $attempt 'workflow.log'
$arguments = @('consumers/lecture-workflow.mjs','prepare',$sourcePath,'--output',$outputPath,'--model',$Model)
if ($Title) { $arguments += @('--title',$Title) }
if ($SourceRole) { $arguments += @('--source-role',$SourceRole) }
# JSON is instruction data, never interpolated shell code. The worker must use
# a normal argument array when invoking the reviewed workflow.
$request = @{command='node';arguments=$arguments;workingDirectory=$repo} | ConvertTo-Json -Depth 5
$prompt = @"
你是此次学科讲义后台生产的独立 Codex EXEC。工作流和范围已经核对。
只执行下面指定的现有工作流命令并等待它完成。用 PowerShell 参数数组，不把 JSON 字符串拼成 shell 代码。
不要修改源码、规则、输入材料、候选计划或产物；不要运行 import、feedback、RemNote 写入、Git 提交或网络发布。不要创建新 Thread，不要更改任何全局配置。
执行日志保存至 $workflowLog，终端只查看退出状态和最新短进度。首次调用允许长任务；如果取得 session id，持续轮询直到完成。日志有进展时不得仅因耗时终止。
失败时保留原始错误并返回，不自行修复。成功时只读取 validation.json 的计数和状态。不要把原文、图片、完整计划或日志带入回复。
最后返回简短 JSON，包含 status、output、questions、with_answers、error（无则null）。自动校验成功不等于用户接受。
$request
"@
$prompt | & codex exec --ephemeral --json --sandbox danger-full-access -c 'approval_policy="never"' --cd $repo --model $Model --output-last-message (Join-Path $attempt 'result.json') - 1> (Join-Path $attempt 'events.jsonl') 2> (Join-Path $attempt 'stderr.log')
$code = $LASTEXITCODE
if (Test-Path -LiteralPath (Join-Path $attempt 'result.json')) { Copy-Item -LiteralPath (Join-Path $attempt 'result.json') -Destination (Join-Path $outputPath 'exec-result.json') }
@{exitCode=$code;attempt=$attempt;finishedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputPath 'exec-exit.json') -Encoding utf8
exit $code
