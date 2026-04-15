# GitHub 仓库同步说明

## 仓库地址

- **远程仓库**：<https://github.com/feezy777/NeuroGraphIQ_KG>
- **默认分支**：`main`
- **说明**：本机工程目录名为 `NeuroGraphIQ_KG_V2`，与上述公开仓库对应；推送时使用 `git push origin HEAD:main --force` 可将当前分支内容**完全覆盖**远程 `main` 上的历史与文件树（请仅在确认无协作冲突时使用）。

## 本次同步要点（NeuroGraphIQ KG 工作台方向）

- **导入 → 解析（Excel 优先）→ 统一中间表示**：解析结果供后续脑区 / 回路 / 连接等中心消费。
- **脑区提取中心**：文件抽取、文本抽取、DeepSeek 直接生成；结果表格展示与版本管理。
- **DeepSeek**：全局配置与弹窗内连接参数（API Key、Base URL、Model、Temperature 等）；可选个性化配置（Profile）；预设与自定义 Prompt；请求侧 `deepseek_override` 与后端 `resolve_deepseek_config` 合并。
- **本地规则抽取**：基于内置脑区知识库与表格/段落/全文多路径匹配，提高抽取完整性。
- **其他**：Neo4j 导出脚本与示例 Cypher、Flask Dashboard、运行时配置等。

## 本地启动（Web 工作台）

```powershell
Set-Location -Path "<你的仓库根目录>"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.ui.run_dashboard
```

浏览器访问：`http://127.0.0.1:8899`

## 安全提示

- `configs/local/runtime.local.yaml` 可能包含数据库口令或 API Key；若仓库为**公开**仓库，请勿提交真实密钥，或使用占位符并在本地单独维护私密配置。
- 强制推送会改写远程 `main` 历史，团队其他成员需 `git fetch` 后按需 `reset`/`rebase`，避免重复合并旧历史。

## 维护者常用命令

```powershell
git status
git add -A
git commit -m "描述本次变更"
git push origin HEAD:main --force
```

（将 `HEAD` 换为当前要发布分支名亦可。）
