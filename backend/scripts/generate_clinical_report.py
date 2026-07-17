"""Generate a 2-page clinical brain analysis PDF report using DeepSeek v4 pro.

Combines system data (symptom query results + circuit analysis) with
DeepSeek's medical knowledge for EEG, neurotransmitters, circulation,
peripheral organs, and peripheral nerves.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_providers.factory import get_llm_provider
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]

PROMPT = """You are a senior clinical neuroscientist writing a comprehensive brain analysis report. You are given:

1. A patient symptom summary from a clinical Q&A session
2. Matching brain circuits from a knowledge graph system
3. A connectivity graph summary

Generate a detailed clinical analysis report in MARKDOWN format covering ALL of the following sections. Write in Chinese (Simplified). Keep it concise enough to fit 2 pages of A4 when rendered as PDF.

---

# 脑部综合分析报告

**生成时间**: {timestamp}
**分析模型**: DeepSeek v4 Pro
**数据来源**: NeuroGraphIQ 知识图谱 + 临床知识库

---

## 一、症状问答总结

### 患者主诉
{summary}

### 系统匹配回路
系统知识图谱匹配到 **{circuit_count}** 个相关脑回路，核心回路包括：
{circuit_list}

---

## 二、脑回路系统分析

### 2.1 核心脑回路受累 (1.1)

基于系统匹配的回路图数据（{node_count}个节点，{edge_count}条连接），分析帕金森病涉及的基底节-丘脑-皮层运动回路的功能异常机制。包括：
- 直接通路（D1受体介导）与间接通路（D2受体介导）的失衡
- 黑质致密部多巴胺能神经元退行性变导致的纹状体输出异常
- 小脑-丘脑-皮层回路在运动协调中的代偿机制
- 脑干回路（脑桥脚核、中缝核）在姿势控制和步态中的作用

### 2.2 脑电活动改变 (1.2)

基于临床研究知识分析：
- PD患者皮层β波段（13-30Hz）过度同步化及其与运动迟缓的关系
- 丘脑底核局部场电位中的振荡异常
- REM睡眠行为障碍的多导睡眠图特征
- 基底节-皮层网络的异常耦合

### 2.3 神经递质系统受累 (1.3)

- 多巴胺：黑质-纹状体通路退变(>50-70%丧失才出现症状)
- 乙酰胆碱：纹状体胆碱能中间神经元相对过度活跃（多巴胺-乙酰胆碱失衡）
- 5-羟色胺：中缝核变性导致抑郁、睡眠障碍
- 去甲肾上腺素：蓝斑变性导致自主神经功能障碍
- 谷氨酸/GABA：基底节输出核团功能异常

---

## 三、循环系统影响

### 3.1 脑动脉系统

- Willis环及相关动脉（大脑中动脉、大脑后动脉）灌注基底节区
- 黑质、纹状体的血液供应特点
- 脑血管自动调节功能与PD相关的可能改变

### 3.2 脑静脉系统

- 深部脑静脉（大脑内静脉、基底静脉）引流基底节区
- 静脉回流障碍与脑铁沉积增加的潜在关联

### 3.3 脑淋巴系统（类淋巴系统）

- 脑膜淋巴管在α-突触核蛋白清除中的作用
- 类淋巴系统功能障碍与PD病理蛋白聚集的关联

### 3.4 脑脊液循环

- 脑脊液中α-突触核蛋白作为生物标志物
- 脑室系统与中脑导水管周围区域的病理改变

---

## 四、可能受累的外周器官

- **消化系统**：肠神经系统α-突触核蛋白沉积（Braak分期最早受累部位），便秘作为前驱症状
- **心血管系统**：心脏交感神经末梢去神经支配，体位性低血压
- **嗅觉系统**：嗅球和嗅前核α-突触核蛋白病理
- **皮肤**：表皮神经纤维α-突触核蛋白沉积作为潜在活检标志物
- **泌尿系统**：膀胱逼尿肌过度活动

---

## 五、外周神经系统分析

- 迷走神经背核受累（Braak第1期），影响副交感传出
- 肠神经系统独立于中枢的病理变化
- 交感神经节（腹腔神经节、颈上神经节）α-突触核蛋白沉积
- 心脏交感神经末梢FDOPA-PET显示摄取减少
- 皮肤神经纤维密度降低及磷酸化α-突触核蛋白沉积

---

## 六、综合结论

上述分析整合了NeuroGraphIQ知识图谱的回路匹配结果（系统数据）与临床神经科学知识（模型补充）。该患者临床表现高度符合**帕金森病**的Braak病理分期模式，涉及从外周（肠神经、嗅神经）到中枢（脑干→中脑→皮层）的进行性α-突触核蛋白病理扩散。

**建议**: 神经内科进一步评估，包括DaTSCAN、心脏MIBG显像、多导睡眠图及神经心理学评估。

---

Generate ONLY the markdown report content (no preamble, no "here is the report"). Start with "# 脑部综合分析报告".
"""


async def main():
    settings = get_settings()
    api_key = settings.deepseek_api_key
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not set")
        sys.exit(1)

    # Load report data
    data_path = BACKEND_DIR / "data" / "symptom_full_report_data.json"
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    summary = data["summary"]
    circuits = data["circuits"]
    circuit_count = len(circuits)
    graph = data["graph_summary"]

    # Build circuit list string
    circuit_lines = []
    for i, c in enumerate(circuits[:10], 1):
        circuit_lines.append(f"{i}. **{c['name']}** (匹配度={c['score']:.0%}, 步骤={c['step_count']}, 功能={c['function_count']})")
    circuit_list = "\n".join(circuit_lines)

    # Build prompt
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = PROMPT.format(
        timestamp=timestamp,
        summary=summary,
        circuit_count=circuit_count,
        circuit_list=circuit_list,
        node_count=graph["node_count"],
        edge_count=graph["edge_count"],
    )

    print(f"Prompt length: {len(prompt)} chars")
    print(f"Circuits: {circuit_count}")
    print(f"Calling DeepSeek v4 Pro...")

    provider = get_llm_provider("deepseek")
    model = "deepseek-chat"

    result = await provider.complete_text(
        model=model,
        system_prompt="You are a senior clinical neuroscientist. Generate professional medical analysis reports in Chinese. Output ONLY clean markdown, no JSON wrapper.",
        user_prompt=prompt,
        temperature=0.3,
        max_tokens=8000,
        timeout_seconds=180,
    )

    if not result.transport_ok or not result.raw_text:
        print(f"ERROR: {result.error}")
        sys.exit(1)

    report_md = result.raw_text.strip()
    if report_md.startswith("```"):
        report_md = report_md.split("\n", 1)[1]
        if report_md.endswith("```"):
            report_md = report_md[:-3]

    # Save markdown
    md_path = BACKEND_DIR / "docs" / "brain_3d" / "clinical_brain_analysis_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Markdown saved: {md_path}")
    print(f"Report length: {len(report_md)} chars")

    # Save JSON version
    json_path = BACKEND_DIR / "data" / "brain_spatial" / "clinical_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "generated_at": timestamp,
                "model": model,
                "data_source": "NeuroGraphIQ KG + DeepSeek Medical Knowledge",
            },
            "report_markdown": report_md,
        }, f, ensure_ascii=False, indent=2)
    print(f"JSON saved: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
