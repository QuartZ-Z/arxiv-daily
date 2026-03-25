#!/usr/bin/env python3
"""
规则过滤模块 - 带历史Top论文追踪
"""
import yaml
import json
import logging
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

def load_config():
    config_path = SCRIPT_DIR / 'config.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_state():
    data_dir = SCRIPT_DIR / 'data'
    state_path = data_dir / 'state.json'
    if state_path.exists():
        with open(state_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'top_paper_ids': [], 'last_removed_ids': []}

def load_papers(raw_file):
    """加载原始论文数据"""
    with open(raw_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_historical_papers(state):
    """加载历史已处理论文"""
    last_processed = state.get('last_processed_papers', '')
    if last_processed and Path(last_processed).exists():
        with open(last_processed, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def deduplicate_papers(papers):
    """去重：保留最新的"""
    seen = {}
    for p in papers:
        arxiv_id = p.get('arxiv_id', '')
        if arxiv_id:
            if arxiv_id not in seen:
                seen[arxiv_id] = p
            else:
                existing_date = seen[arxiv_id].get('submittedDate', '')
                new_date = p.get('submittedDate', '')
                if new_date > existing_date:
                    seen[arxiv_id] = p
    return list(seen.values())

def filter_by_time_window(papers, days=30):
    """过滤超出时间窗口的论文，返回保留的论文和ID列表"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    filtered = [p for p in papers if p.get('submittedDate', '') >= cutoff]
    removed_ids = [p.get('arxiv_id') for p in papers if p.get('submittedDate', '') < cutoff]
    logger.info(f'Time window filter: {len(papers)} -> {len(filtered)} (removed {len(removed_ids)})')
    return filtered, removed_ids

def filter_by_keywords(papers, keywords):
    """关键词过滤"""
    filtered = []
    for p in papers:
        text = f"{p.get('title', '')} {p.get('abstract', '')}".lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(p)
    logger.info(f'Keyword filter: {len(papers)} -> {len(filtered)}')
    return filtered

def filter_by_length(papers, min_length=200):
    """摘要长度过滤"""
    filtered = [p for p in papers if len(p.get('abstract', '')) >= min_length]
    logger.info(f'Length filter: {len(papers)} -> {len(filtered)}')
    return filtered

def filter_winner_papers(papers, top_paper_ids):
    """排除已入选过Top的论文"""
    filtered = [p for p in papers if p.get('arxiv_id') not in top_paper_ids]
    logger.info(f'Winner filter: {len(papers)} -> {len(filtered)} (excluded {len(papers) - len(filtered)} historical winners)')
    return filtered

def main(raw_file):
    """主函数"""
    logger.info('=' * 50)
    logger.info('Starting filter process')
    logger.info(f'Script directory: {SCRIPT_DIR}')
    logger.info('=' * 50)
    
    config = load_config()
    state = load_state()
    
    new_papers = load_papers(raw_file)
    logger.info(f'Loaded {len(new_papers)} new papers from {raw_file}')
    
    historical_papers = load_historical_papers(state)
    logger.info(f'Loaded {len(historical_papers)} historical papers')
    
    all_papers = historical_papers + new_papers
    logger.info(f'Merged: {len(all_papers)} total papers')
    
    papers = deduplicate_papers(all_papers)
    logger.info(f'After dedup: {len(papers)} papers')
    
    # 时间窗口过滤 - 同时获取被移除的论文ID
    papers, removed_ids = filter_by_time_window(papers, config['time_window_days'])
    
    papers = filter_by_keywords(papers, config['filters'])
    papers = filter_by_length(papers)
    
    # 获取并清理历史Top论文ID
    top_paper_ids = set(state.get('top_paper_ids', []))
    original_top_count = len(top_paper_ids)
    
    if removed_ids:
        removed_set = set(removed_ids)
        top_paper_ids = top_paper_ids - removed_set
        logger.info(f'Cleaned {original_top_count - len(top_paper_ids)} top paper IDs out of time window')
    
    papers = filter_winner_papers(papers, top_paper_ids)
    
    # 确保目录存在
    data_dir = SCRIPT_DIR / 'data'
    processed_dir = data_dir / 'processed'
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    processed_file = processed_dir / f'papers_{timestamp}.json'
    with open(processed_file, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    
    logger.info(f'Saved {len(papers)} filtered papers to {processed_file}')
    
    # 更新状态
    state['last_processed_papers'] = str(processed_file)
    state['top_paper_ids'] = list(top_paper_ids)
    state['last_removed_ids'] = removed_ids  # 用于清理LLM缓存
    
    state_path = data_dir / 'state.json'
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    
    logger.info('Filter process completed')
    return papers, str(processed_file)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        raw_dir = SCRIPT_DIR / 'data' / 'raw'
        files = sorted(raw_dir.glob('papers_*.json'))
        if files:
            main(str(files[-1]))
        else:
            logger.error('No raw data files found')
