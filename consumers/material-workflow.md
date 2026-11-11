# 通用资料导入 RemNote

学科讲义使用[第三入口](lecture-workflow.md)：复用本文全部通用阶段，再增加章内分类、原图题面／答案及新形式试导反馈。

将文档、网站 Markdown 页面集合和矢量思维导图 PDF 转换为可检查的 Markdown 大纲、离线阅读页和标准 RemNote 包，再通过现有 Bulk Importer MCP 导入。各类型共用同一个命令、来源去重、目标库检查和完整回读；每份资料只创建新的书籍或资料子树。

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

### 已生产的 Markdown 数理讲义

已有完整嵌套大纲、无需重新分类或改写的讲义，沿用同一入口并指定 `--layout outline`：

```powershell
node consumers/material-workflow.mjs prepare '<原始讲义.md>' --layout outline --output '<D:/Artifacts 下的产物目录>'
node consumers/material-workflow.mjs import '<原始讲义.md>' --layout outline --output '<同一目录>' --kb-id '<已核对库 ID>'
```

使用预览 HTML 对应的原始 Markdown，不解析渲染后的公式占位符。初始 H1 作为唯一导入根标题，后续标题和列表按源父子关系成为普通节点；一个列表项对应一个 Rem，其多段说明、多行公式和代码仍在同一节点。编号列表保留原编号。公式沿用原生 LaTeX，图片沿用已有托管媒体及字节校验，不添加批注、卡片、分类或题目字段，不调用模型重新判断大纲。

本地准备重新解析原文件，逐项比较顺序、父节点、正文、换行、公式模式和媒体，再运行标准包校验与 KaTeX。`source-outline.md` 是原稿副本；离线 `preview.html` 和 JSON 证据与正文分开。导入继续使用既有来源去重、目标库检查、单写入者、断点恢复及全部节点/媒体回读。自动通过不代替用户对显示效果的反馈。

当前适配列表大纲及其节点内连续段落、公式、围栏代码和本地图片。父节点正文在子列表后继续、缩进不明、未闭合公式/代码、多 H1 根、块引用、表格或缺失图片会停止；这些结构需要先扩展适配，不能悄悄改写或丢弃。该模式与基于原 PDF 裁图并分类的学科讲义入口分开，后者的题面/答案图片规则不用于改造已生产的 Markdown 正文。

讲义大纲和通用 Markdown 中的 Mermaid 围栏，以及 HTML 中保留源码的 Mermaid 块，导入为可编辑的 Mermaid 节点。图块在列表项内与正文并存时，作为该项的子节点，按源文顺序放置后续段落。目标知识库须启用 [RemNote 官方 Mermaid 插件](https://github.com/remnoteio/remnote-official-plugins/tree/main/mermaid)。导入器在写入前检查 Mermaid Power-up，回读时同时核对源码和 Power-up。流程适用于新导入，旧导入记录按原包保留。

### 网站页面集合与目录整理

Obsidian Publish 等网站已有原始 Markdown 时，先冻结已授权范围的页面和媒体，再把 `snapshot.json` 直接交给通用入口。旧 `materials.publish_snapshot` 命令继续兼容：

```powershell
node consumers/material-workflow.mjs prepare '<本地 source/snapshot.json>' --output '<产物目录>' --title '<资料标题>'
node consumers/material-workflow.mjs validate '<本地 source/snapshot.json>' --output '<产物目录>'
node consumers/material-workflow.mjs import '<本地 source/snapshot.json>' --output '<产物目录>' --kb-id '<目标库 ID>'
```

该适配器不联网、不接收密码。快照包含 `site`、`pages`（每页的站内 `path`、本地相对 `file`、原字节 `sha256`）、下载失败清单；旁边的 `cache.json` 为站内路径索引，`assets.json` 保存每份已下载媒体的站内路径/URL、本地相对文件和 SHA-256。可用 `selectedPaths`、`assetsSha256`、`cacheSha256` 固定完整选择及关联清单。下载阶段必须先取得适用授权，密码与签名 URL 不进入快照。

每个来源页面为一个 Document，目录保留来源路径，页内标题和列表为普通大纲。只合并同名且原文字节完全一致的页面；别名路径保留在独立凭据中。Wiki 链接转换为精确内部引用，源站未发布的目标保留原链接。所有可用图片必须落为原生图片，图片出现次数与来源归一化记录相等；缺失附件保留原名与位置。交互网页、视频及 PDF 保留原链接，PDF 正文可另用既有 PDF 流程导入同一资料根下。SVG 以隔离、禁止联网的 Chrome 截图保留嵌入文字，并附原 SVG 链接供查看动画；原文件、截图及哈希记录均留在本地。需要 Chrome 的 SVG 转换使用 `RBI_RENDER_CHROME` 或本机安装位置，不操作现有浏览器窗口。

目录可以按学科、课程或主题重组。首次准备时可加 `--catalog '<目录方案.json>'`；正文、页面 ID、页内大纲和引用不变。方案中的 `containers` 声明新增目录，`pages` 必须把每篇去重后的来源页面恰好安置一次。`parent` 可以是新增目录 ID，也可以是另一篇页面的来源路径。生成器移除未使用的原站目录容器，拒绝遗漏、重复归属、缺失父节点和环路。一个通用示例：

```json
{
  "containers": [{"id":"catalog-methods","title":"研究方法","parent":null}],
  "pages": [
    {"path":"站内旧目录/方法.md","parent":"catalog-methods"},
    {"path":"零散页面/示例.md","parent":"站内旧目录/方法.md"}
  ]
}
```

`catalog-plan.json` 保留完整方案与其来源哈希；后续校验和导入重新核对方案与每篇页面的实际归属。已完成的导入不能通过重跑 `prepare/import` 再复制一次；使用既有 `restructure` 做只改结构的修订，并保留旧容器的恢复位置。这次剥茧物理资料的“主题目录＋正文保留＋旧目录可恢复”做法适用于其他网站，无需硬编码学科名称。

URL 采集、登录或站点 API 下载是输入获取阶段，当前命令不自动爬取任意 URL，也不读取浏览器登录态。普通网页可先保存为带媒体的本地 HTML；有原始 Markdown 的网站优先用上述页面集合，避免丢失公式、内部链接和附件。

### 思维导图／大纲图谱 PDF

对于文字、连线和节点框仍是矢量对象的 PDF，使用：

```powershell
node consumers/material-workflow.mjs prepare '<图谱.pdf>' --layout mindmap --output '<产物目录>'
node consumers/material-workflow.mjs import '<图谱.pdf>' --layout mindmap --output '<产物目录>' --kb-id '<目标库 ID>'
```

该模式要求每页有单个可辨识的彩色根框，从 PDF 原始连接线恢复树形父子关系，支持左右分支、下划线、方框／圆角框及填充轮廓连线。同一水平线上的分叉点保持父子关系，不能把父节点和与它齐平的一个子节点合并。只有没有分叉的同基线标签延续才可合并。

分页只服务版面：全书只有一个根，页根不成为内容容器。总览与详细页的重复章节按明确章序或相同标题合并，章节为 Document，内部为普通大纲；同父下完全相同的内容合并并保留来源去向。整页图只用于来源核验，不重复插入已经拆好的正文。

原生文字直接提取。嵌入图片先合成自己的 PDF 透明遮罩，再铺白底，避免黑图、空白和邻近文字污染。MinerU 对每幅图片做 OCR；Codex EXEC 根据真实像素区分文字／公式、教学绘图和装饰图标。文字／公式变成可编辑文本与原生 LaTeX，截图中的多行内容成为对应主题下的并列节点；内嵌符号依据原字符坐标插回文字间隙。全部转写再逐图校对像素，KaTeX 语法通过不能替代这一步。真正教学绘图保留图片，纯装饰图标不进入笔记。

远离候选标签下划线的浮动图片不能凭最近的下一条线归属。先核对源箭头；无法唯一确定时，用实际图片、原页上下文和有界真实候选主题做视觉归属，记录在 `mindmap-attachments.json`。`readable-tree.json` 保存合并后的单树和来源去向；`mindmap-readable-inputs.json` 冻结识别、分类、转写和归属凭据。`mindmap-readable-audit.json` 从原 PDF 重建拓扑与图片遮罩合成，检查每个来源片段均显示或有明确合并／装饰排除原因，并继续通用包校验及全部 RemNote 节点／媒体回读。扫描图、根不明确、断线或带环的关系图明确停止，不把 OCR 阅读顺序当成拓扑。

修复自己已导入且被退回的结果时，先在新产物目录从原始资料重新生成，通过后显式指定旧根和恢复容器：

```powershell
node consumers/material-workflow.mjs import '<图谱.pdf>' --layout mindmap --output '<修正产物目录>' --kb-id '<目标库 ID>' --replace-root '<旧书根 ID>' --archive-parent-rem-id '<库根级 trash ID>'
```

替换先验证同来源完成凭据、旧根精确 ID 和父节点。新树完成全部回读后，旧树整棵移入恢复容器，随后才更新来源登记；`replacement-recovery.json` 保留旧回执和移动前后状态。归档失败可重跑恢复，新包不再创建第二棵；原包和旧树不删除。用户材料的批量替换仍须有明确授权，此参数不扩张授权。

## 输入与结构

| 输入 | 提取方式 | 边界 |
| --- | --- | --- |
| PDF | 既有 MinerU 精准 API；按实际文件大小和页数分块 | 每块最多 150 页、180 MB；逐页检查 OCR 覆盖，保留原始块与图片 |
| PNG/JPEG/JP2/WebP/GIF/BMP | MinerU 精准 API | 原图和识别结果保留；不假设动画或交互内容可被完整表达 |
| DOC/DOCX、PPT/PPTX | MinerU 精准 API | 面向可见文档内容；文件超过上传限制时明确停止，修订历史和演示动画不属于笔记正文 |
| EPUB | 既有本地 EPUB 提取器 | 按实际逻辑标题拆分，不按 XHTML 文件数拆书；不完整提取会停止 |
| Markdown、UTF-8 TXT | 本地解析 | 代码保留；TXT 不猜测编码；原有标题/列表作为结构依据 |
| HTML | 本地解析 | 保留正文、标题、公式、表格和本地图片；外部图片需随资料落地，无法表达的嵌入对象明确停止 |
| 网站 Markdown 快照／页面集合 JSON | 原始 Markdown＋站内路径与媒体凭据 | 自动识别 `site/pages` 清单；真实层级、内部引用、SVG 预览、缺失附件位置；可用完整目录方案重组 |
| 矢量思维导图／大纲图谱 PDF | `--layout mindmap`，PDF 连线＋原生文字＋公式图片 OCR | 跨页单树、章节合并、原生公式和并列节点；只保留教学绘图；扫描图、断线或环路停止 |

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
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/source_outline_test.py
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/publish_snapshot_test.py
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/material_catalog_test.py
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/mindmap_test.py
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/mindmap_readable_test.py
& 'D:\AppData\RemNoteBulkImporter\material-venv\Scripts\python.exe' test/material_replacement_test.py
npm test
npm run typecheck
npm run build
node node_modules/@remnote/plugin-sdk/scripts/index.js validate
```

`test/material_canaries.py <产物目录>` 生成生物、历史、化学、地理、文学、计算机和天文学的独立格式样本；需要额外安装 `python-pptx`。`test/material_regression.py <旧验收目录> <新回归目录>` 使用冻结的原始物理书数据和已验证结构检查转换器回归，不再次导入旧书。
