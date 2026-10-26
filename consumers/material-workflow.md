# 通用资料导入 RemNote

将本地图文资料转换为可检查的 Markdown 大纲、离线阅读页和标准 RemNote 包，再通过现有 Bulk Importer MCP 导入。每份资料只创建新的书籍或资料子树。

## 使用

在本仓库运行：

```powershell
pwsh -NoProfile -File consumers/Install-MaterialRuntime.ps1
node consumers/material-workflow.mjs prepare 'D:\Downloads\资料.pdf' --title '资料名称'
node consumers/material-workflow.mjs import 'D:\Downloads\资料.pdf' --kb-id '<目标库 ID>'
```

`prepare` 完成提取、目录定位、大纲组织、原文覆盖校验、公式检查和本地预览。`import` 只接受已校验的包；写入前核对当前知识库，完成后要求逐节点与图片字节回读。`status` 查看当前连接及库 ID。

要放在已有 Document 下，先通过本地 RemNote MCP 核对该 Document，再在 `import` 后添加 `--parent-rem-id '<目标 Document 的 Rem ID>'`。导入会直接在此父节点下创建书根，恢复和去重同时检查父节点；不指定时创建库根级书根。

其他命令：`extract` 仅提取；`validate` 重新校验本地产物。`--output` 指定独立运行目录；同一资料所有阶段使用同一个目录。`--model` 只指定剩余 Codex EXEC 工作的模型，已经校验的生产结果继续复用，并保留其实际模型记录。

大量公式和多层目录的书籍可显式加 `--model gpt-6-sol`。未指定模型时沿用共享 Codex EXEC transport 的默认配置，不修改用户的全局模型设置。

默认产物在 `D:\Artifacts\RemNoteBulkImporter\materials\<来源哈希前缀>`。正文见 `markdown/阅读目录.md`、`markdown/分篇`、`markdown/全书大纲.md` 和 `preview.html`；检查证据独立保存在 JSON 文件中。`validation.json` 代表本地验证，只有 `completion.json` 及 MCP 完成回执代表实际导入完成。

## 输入与结构

| 输入 | 提取方式 | 边界 |
| --- | --- | --- |
| PDF | 既有 MinerU 精准 API；按实际文件大小和页数分块 | 每块最多 150 页、180 MB；逐页检查 OCR 覆盖，保留原始块与图片 |
| PNG/JPEG/JP2/WebP/GIF/BMP | MinerU 精准 API | 原图和识别结果保留；不假设动画或交互内容可被完整表达 |
| DOC/DOCX、PPT/PPTX | MinerU 精准 API | 面向可见文档内容；文件超过上传限制时明确停止，修订历史和演示动画不属于笔记正文 |
| EPUB | 既有本地 EPUB 提取器 | 按实际逻辑标题拆分，不按 XHTML 文件数拆书；不完整提取会停止 |
| Markdown、UTF-8 TXT | 本地解析 | 代码保留；TXT 不猜测编码；原有标题/列表作为结构依据 |
| HTML | 本地解析 | 保留正文、标题、公式、表格和本地图片；外部图片需随资料落地，无法表达的嵌入对象明确停止 |

MinerU 支持类型与单文件限制以[官方文档](https://mineru.net/apiManage/docs)为依据。凭据继续由既有 OCR runner 获取，工作流不复制或记录密钥。

有纸面目录时沿用到最低一级；没有纸面目录时使用可靠的源标题或书签。扫描器生成的流水号书签不作为目录。确实缺少结构时，Codex EXEC 可识别自然阅读单元并补必要标题，正文保持原文。目录节点为 Document，正文节点为普通大纲节点；书前材料、原目录、附录和答案保留。

正文之前的 Document 标题按实际内容简写，例如“封面”“书名页”“版权页”“前言”“目录”，避免堆叠书名、版次、作者和出版社。标题清洗只作用于书前部分，原始文字保留在 Document 内；正文仍沿用原目录。独立识别出的章节编号与后面的章名归入同一 Document。

中英文章名被目录或正文 OCR 拆成多块时，合并需要正文精确文本证据；连续块还须处于同页、同标题层级，从独立章号开始，中间不能有正文或另一个章号。缺少这些证据时保留分项，不根据题材或预设章数猜测。

Codex EXEC 只输出标题边界和嵌套区间，不重写正文、事实、题目或答案。区间不得跨文档、交叉或改变顺序。公式转换为原生 LaTeX，图片转换为经过哈希验证的托管媒体。合并单元格保存原始 HTML 和 OCR 原图，原生可编辑表示采用展开后的逻辑网格，并在 `representation-notes.json` 中列明。

OCR 公式出现未闭合定界符或无法通过 KaTeX 时，保留原始识别结果，以同块表格原图或 PDF 对应区域截图呈现，不猜改公式。校验会重新证明具体转换错误，并核对原 PDF、页码、坐标和图片字节。没有可证明原图的错误仍会停止。相邻、同来源区域且同大纲父节点的重复图片表示只显示一次；其他节点仍逐项保留。回退明细记录在 `representation-notes.json`，不混入笔记正文。

## 重跑与恢复

- 同一命令再次运行会复用成功 OCR 和已校验的 Codex 结果。来源、提示词或适配器改变时，相关本地阶段重新生成；不直接修补候选正文。
- OCR 的上传批次在轮询前保存。网络中断保留批次，恢复时查询原批次，避免重复提交。
- Codex 调用缺少 `turn.completed`、返回无效结构或调用失败时明确失败；只做有限重试，不切换外部模型 API。
- 同一目标库与来源哈希只有一个导入记录。改变提示词或重新整理不会默默再导入同一本书。已写入内容被用户修改时，由现有 importer 的恢复校验阻止覆盖。
- 导入期间只通过 MCP 查询运行状态；不读取正在写入的 checkpoint 文件。中断后用相同资料、包和库恢复。
- 自动校验覆盖“提取结果到笔记”的完整性，不把 OCR 成功等同于印刷原稿逐字无误。具体 OCR 问题保留来源证据后处理。

已经完成导入的材料应保留原包和完整回读凭据。结构修订包只能改变已审核的层级；如果旧图片检查点的 RichText 哈希无法匹配，整库重构会在写入前停止，不能忽略该校验或把构建通过视为修复成功。对于已确认的少量纯文本边界移动，可通过本地 RemNote MCP 逐项核对原文、原父节点和目标位置，执行后回读；完成记录必须同时保留原始完整回读与精确移动凭据，不冒充一次新的完整批量导入。

已导入资料不会因渲染器后续升级而自动重写。重新生成导致包改变时，来源去重会停止重复导入；应先审查差异并选择明确的修订范围。

## 运行依赖与维护

复用 `D:\Projects\BookSimplifier` 的 OCR runner、`D:\Projects\渐进阅读工作流` 的 EPUB 提取和 Codex EXEC transport、`D:\Projects\HyperskillRemNoteWorkflow` 的原生 RichText/表格表示，以及本仓库的 MCP importer。没有另一套任务控制器。位置可由 `RBI_BOOK_SIMPLIFIER`、`RBI_READING_PROJECT`、`RBI_HYPERSKILL_PROJECT` 指定；运行时可由 `RBI_MATERIAL_PYTHON` 指定。

源码、合成测试在仓库；用户资料、OCR、图片、模型响应、Rem ID、日志和运行状态只在 D 盘产物/运行目录。不得提交用户样本。

验证命令：

```powershell
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/materials_test.py
npm test
npm run typecheck
npm run build
node node_modules/@remnote/plugin-sdk/scripts/index.js validate
```

`test/material_canaries.py <产物目录>` 生成生物、历史、化学、地理、文学、计算机和天文学的独立格式样本；需要额外安装 `python-pptx`。`test/material_regression.py <旧验收目录> <新回归目录>` 使用冻结的原始物理书数据和已验证结构检查转换器回归，不再次导入旧书。
