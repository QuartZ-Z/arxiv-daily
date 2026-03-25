#!/usr/bin/env python3
"""
LLM评分模块 - 带评分缓存
注意：
1. top_paper_ids 更新已移至 cron_job.py，在报告生成成功后执行
2. LLM调用失败时不缓存结果，以便下次重试
"""
import yaml
import json
import os
import time
import logging
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# 获取脚本所在目录作为基准
SCRIPT_DIR = Path(__file__).parent.resolve()
WORKSPACE_DIR = SCRIPT_DIR.parent

# 配置日志
LOG_DIR = SCRIPT_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'run.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 缓存文件路径
LLM_CACHE_FILE = SCRIPT_DIR / 'data' / 'llm_score_cache.json'

def load_env():
    env_path = WORKSPACE_DIR / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"\'')

def load_llm_cache():
    """加载LLM评分缓存"""
    if LLM_CACHE_FILE.exists():
        with open(LLM_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_llm_cache(cache):
    """保存LLM评分缓存"""
    LLM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LLM_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def clean_llm_cache(cache, removed_ids):
    """清理超出时间窗口的缓存"""
    if not removed_ids:
        return cache
    cleaned = {k: v for k, v in cache.items() if k not in removed_ids}
    removed_count = len(cache) - len(cleaned)
    if removed_count > 0:
        logger.info(f'Cleaned {removed_count} cached scores out of time window')
    return cleaned

def call_llm(title, abstract, config):
    """调用LLM进行评分
    
    Returns:
        tuple: (scores_dict, success_bool)
        - 成功时返回 (scores, True)
        - 失败时返回 (error_scores, False)，不会缓存
    """
    base_url = os.environ.get('BaseURL', '')
    api_key = os.environ.get('APIKey', '')
    model_name = os.environ.get('ModelName', 'kimi-k2.5')
    
    if not base_url or not api_key:
        raise ValueError('LLM API configuration missing')
    
    prompt = f"""请根据以下论文信息进行评分：

标题：
{title}

摘要：
{abstract}

请按照以下标准评分（0-10分）：
1. Relevance：
定义：是否属于 AI for Science
评分标准：
+ 0-3：无关
+ 部分相关
+ 明显相关
+ 核心领域

2. Novelty
定义：是否提出新方法/新问题
评分标准：
+ 0-3：已有方法应用
+ 4-6：小改进
+ 7-8：明显创新
+ 9-10：新范式

3. Technical Depth
定义：方法复杂性、理论深度
评分标准：
+ 0-3：浅层应用
+ 4-6：中等
+ 7-8：较深
+ 9-10：高深理论/系统

4. Potential Impact
定义：对科研/工业潜在价值
评分标准：
+ 0-3：有限
+ 4-6：一般
+ 7-8：较大
+ 9-10：可能重要突破

请严格输出JSON，不要包含任何额外内容：

{{
  "relevance": int,
  "novelty": int,
  "technical_depth": int,
  "impact": int,
  "reason": "不超过100字"
}}"""

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config['llm'].get('temperature', 0)
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    
    # 增加超时到120秒
    timeout_seconds = 120
    
    for attempt in range(3):
        try:
            logger.info(f'  Calling LLM (attempt {attempt + 1}/3, timeout={timeout_seconds}s)...')
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result['choices'][0]['message']['content']
                
                try:
                    scores = json.loads(content)
                except json.JSONDecodeError:
                    if '```json' in content:
                        content = content.split('```json')[1].split('```')[0]
                    elif '```' in content:
                        content = content.split('```')[1].split('```')[0]
                    scores = json.loads(content.strip())
                
                final_score = (
                    0.3 * scores['relevance'] +
                    0.3 * scores['novelty'] +
                    0.2 * scores['technical_depth'] +
                    0.2 * scores['impact']
                )
                scores['final_score'] = round(final_score, 2)
                
                return scores, True  # 成功返回
                
        except Exception as e:
            logger.warning(f'  LLM call attempt {attempt + 1} failed: {e}')
            if attempt < 2:
                wait_time = 2 ** attempt
                logger.info(f'  Retrying in {wait_time}s...')
                time.sleep(wait_time)
            else:
                logger.error(f'  LLM call failed after 3 attempts: {e}')
    
    # 所有尝试失败，返回错误分数但不缓存
    error_scores = {
        "relevance": 0,
        "novelty": 0,
        "technical_depth": 0,
        "impact": 0,
        "reason": "LLM call failed - will retry",
        "final_score": 0.0,
        "_error": True  # 标记为错误结果
    }
    return error_scores, False

def main(processed_file):
    """主函数 - 带缓存机制
    
    注意：
    1. 此函数不再更新 top_paper_ids，改由 cron_job.py 在报告生成成功后更新
    2. 这样可以确保报告生成失败时可以重试，不会丢失本次的 top papers
    3. LLM调用失败时不缓存，下次运行会重试
    """
    logger.info('=' * 50)
    logger.info('Starting LLM ranking process (with cache)')
    logger.info(f'Script directory: {SCRIPT_DIR}')
    logger.info('=' * 50)
    
    load_env()
    
    config_path = SCRIPT_DIR / 'config.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    with open(processed_file, 'r', encoding='utf-8') as f:
        papers = json.load(f)
    
    # 加载状态（获取本次被移除的ID）
    state_path = SCRIPT_DIR / 'data' / 'state.json'
    if state_path.exists():
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {}
    removed_ids = state.get('last_removed_ids', [])
    
    # 加载并清理缓存
    cache = load_llm_cache()
    cache = clean_llm_cache(cache, removed_ids)
    
    logger.info(f'Loaded {len(papers)} papers for ranking')
    logger.info(f'LLM cache: {len(cache)} cached scores')
    
    # 区分需要评分的论文和已有缓存的论文
    papers_to_score = []
    cached_papers = []
    failed_papers = []  # 记录失败的论文
    
    for paper in papers:
        arxiv_id = paper.get('arxiv_id', '')
        if arxiv_id and arxiv_id in cache:
            paper['scores'] = cache[arxiv_id]
            cached_papers.append(paper)
        else:
            papers_to_score.append(paper)
    
    logger.info(f'Using cache for {len(cached_papers)} papers')
    logger.info(f'Need to score {len(papers_to_score)} new papers')
    
    # 只对未缓存的论文调用LLM
    newly_scored = []
    for i, paper in enumerate(papers_to_score):
        arxiv_id = paper.get('arxiv_id', '')
        logger.info(f'Scoring paper {i+1}/{len(papers_to_score)}: {arxiv_id}')
        
        try:
            scores, success = call_llm(
                paper.get('title', ''),
                paper.get('abstract', ''),
                config
            )
            paper['scores'] = scores
            
            if success:
                # 只有成功时才缓存
                if arxiv_id:
                    cache[arxiv_id] = scores
                newly_scored.append(paper)
                logger.info(f'  ✓ Scored successfully: {scores.get("final_score", 0)}')
            else:
                # 失败时不缓存，记录以便重试
                failed_papers.append(paper)
                logger.warning(f'  ✗ Scoring failed, will retry next time')
            
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f'  Unexpected error scoring paper {arxiv_id}: {e}')
            paper['scores'] = {
                "relevance": 0,
                "novelty": 0,
                "technical_depth": 0,
                "impact": 0,
                "reason": f"Error: {str(e)[:50]}",
                "final_score": 0.0,
                "_error": True
            }
            failed_papers.append(paper)
    
    # 如果有失败的论文，记录警告
    if failed_papers:
        logger.warning(f'⚠️ {len(failed_papers)} papers failed to score and will be retried next run')
    
    # 合并所有论文（已缓存 + 新评分成功），不包括失败的
    all_ranked_papers = cached_papers + newly_scored
    
    # 按最终分数排序
    all_ranked_papers.sort(key=lambda x: x['scores']['final_score'], reverse=True)
    
    # 取Top K
    top_k = config.get('top_k', 5)
    top_papers = all_ranked_papers[:top_k]
    
    logger.info(f'Selected top {len(top_papers)} papers')
    logger.info(f'Saved {len(cache)} scores to cache')
    
    # 确保目录存在
    processed_dir = SCRIPT_DIR / 'data' / 'processed'
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ranked_file = processed_dir / f'ranked_{timestamp}.json'
    with open(ranked_file, 'w', encoding='utf-8') as f:
        json.dump(all_ranked_papers, f, ensure_ascii=False, indent=2)
    
    top_file = processed_dir / f'top_{timestamp}.json'
    with open(top_file, 'w', encoding='utf-8') as f:
        json.dump(top_papers, f, ensure_ascii=False, indent=2)
    
    logger.info(f'Saved ranked papers to {ranked_file}')
    logger.info(f'Saved top papers to {top_file}')
    
    # 保存缓存（不更新 top_paper_ids，由调用方在成功后再更新）
    save_llm_cache(cache)
    
    # 如果所有需要评分的论文都失败了，抛出异常以标记任务失败
    if papers_to_score and len(failed_papers) == len(papers_to_score):
        logger.error('❌ All LLM scoring attempts failed!')
        raise RuntimeError(f'All {len(failed_papers)} LLM scoring attempts failed')
    
    logger.info('Ranking process completed')
    return top_papers

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        proc_dir = SCRIPT_DIR / 'data' / 'processed'
        files = sorted(proc_dir.glob('papers_*.json'))
        if files:
            main(str(files[-1]))
        else:
            logger.error('No processed data files found')
