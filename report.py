#!/usr/bin/env python3
"""
报告生成模块 - 生成带中文翻译的 arXiv 日报
"""
import json
import yaml
import logging
import time
import requests
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
WORKSPACE_DIR = SCRIPT_DIR.parent

config_path = SCRIPT_DIR / 'config.yaml'
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

def load_env(workspace_dir):
    """加载环境变量"""
    env_path = workspace_dir / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    value = value.strip('"\'')
                    os.environ[key] = value


def translate_abstract(title, abstract, workspace_dir):
    """使用LLM翻译摘要
    
    Args:
        title: 论文标题
        abstract: 论文摘要
        workspace_dir: 工作目录
    
    Returns:
        str: 中文翻译
    """
    load_env(workspace_dir)
    
    base_url = os.environ.get('BaseURL', 'https://cloud.infini-ai.com/maas/v1')
    api_key = os.environ.get('APIKey', '')
    model_name = os.environ.get('ModelName', 'kimi-k2.5')
    
    if not api_key:
        return "【中文翻译待生成】"
    
    prompt = f"""请将以下标题为《{title}》的英文论文摘要翻译成中文：

{abstract}

要求：
1. 保持学术语言的准确性
2. 保留专业术语
3. 语言流畅自然

直接输出中文翻译，不要包含任何额外说明。"""

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    
    data = {
        'model': model_name,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': config['llm'].get('temperature', 0),
        'max_tokens': 2000
    }
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                f'{base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.error(f'Translation error (attempt {attempt + 1}): {e}')
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    
    return "【中文翻译生成失败】"


def generate_report(top_papers, stats, script_dir, workspace_dir):
    """生成报告
    
    Args:
        top_papers: Top论文列表
        stats: 统计信息字典
        script_dir: 脚本目录
        workspace_dir: 工作目录
    
    Returns:
        str: 报告文件路径
    """
    logger.info('>>> Generating report with translations')
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    report_lines = [
        f"# Arxiv Daily Report ({today})",
        "",
        "## 1. 今日概览",
        f"- 抓取论文数：{stats['raw_count']}",
        f"- 过滤后：{stats['filtered_count']}",
        f"- 评分后：{stats['ranked_count']}",
        f"- 推荐论文数：{len(top_papers)}",
        "",
        "---",
        "",
        "## 2. 推荐论文",
        ""
    ]
    
    for i, paper in enumerate(top_papers, 1):
        arxiv_id = paper.get('arxiv_id', '')
        title = paper.get('title', 'N/A')
        authors = paper.get('authors', [])
        authors_str = ', '.join(authors[:3]) + (' et al.' if len(authors) > 3 else '')
        date = paper.get('submittedDate', '')[:10]
        abstract = paper.get('abstract', 'N/A')
        scores = paper.get('scores', {})
        
        logger.info(f'Translating abstract {i}/{len(top_papers)}: {title[:50]}...')
        chinese_abstract = translate_abstract(title, abstract, workspace_dir)
        
        report_lines.extend([
            f"### {i}. {title}",
            "",
            f"- **Authors:** {authors_str}",
            f"- **Date:** {date}",
            f"- **Link:** https://arxiv.org/abs/{arxiv_id}",
            "",
            "#### 英文摘要",
            "",
            abstract,
            "",
            "#### 中文摘要",
            "",
            chinese_abstract,
            "",
            "#### 评价",
            "",
            scores.get('reason', 'N/A'),
            "",
            "#### 评分",
            "",
            f"- **Relevance:** {scores.get('relevance', 'N/A')}",
            f"- **Novelty:** {scores.get('novelty', 'N/A')}",
            f"- **Technical Depth:** {scores.get('technical_depth', 'N/A')}",
            f"- **Impact:** {scores.get('impact', 'N/A')}",
            f"- **Final Score:** {scores.get('final_score', 'N/A')}",
            ""
        ])
    
    report = '\n'.join(report_lines)
    
    # 保存报告
    outputs_dir = script_dir / 'outputs'
    outputs_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    report_file = outputs_dir / f'report_{today_str}.md'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info(f'Report generated: {report_file}')
    return str(report_file)


if __name__ == '__main__':
    print("This module is not meant to be run directly.")
    print("Use: from report import generate_report")
