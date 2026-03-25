#!/usr/bin/env python3
"""
Arxiv Daily - 主流程入口
完整自动化流程：抓取 → 过滤 → 评分 → 生成报告 → 上传 → 通知
"""
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# 获取脚本所在目录作为工作目录基准
SCRIPT_DIR = Path(__file__).parent.resolve()
WORKSPACE_DIR = SCRIPT_DIR.parent

# 添加当前目录到路径
sys.path.insert(0, str(SCRIPT_DIR))

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


def update_state(top_papers, script_dir):
    """更新状态文件
    
    Args:
        top_papers: Top论文列表
        script_dir: 脚本目录
    """
    logger.info('>>> Updating state')
    
    data_dir = script_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / 'state.json'
    
    if state_path.exists():
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {'top_paper_ids': [], 'last_removed_ids': []}
    
    current_top_ids = [p['arxiv_id'] for p in top_papers if p.get('arxiv_id')]
    existing_top_ids = set(state.get('top_paper_ids', []))
    all_top_ids = existing_top_ids | set(current_top_ids)
    state['top_paper_ids'] = list(all_top_ids)
    state['last_success_time'] = datetime.now().isoformat()
    
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    
    logger.info(f'Updated top_paper_ids: {len(current_top_ids)} new, {len(all_top_ids)} total')
    return len(all_top_ids)


def main():
    """主流程"""
    logger.info('=' * 60)
    logger.info('Arxiv Daily - Starting Automated Workflow')
    logger.info(f'Time: {datetime.now().isoformat()}')
    logger.info(f'Script directory: {SCRIPT_DIR}')
    logger.info('=' * 60)
    
    top_papers = None
    report_file = None
    
    try:
        # Step 1: 抓取论文
        logger.info('\n>>> Step 1: Fetching papers from arXiv')
        import fetch
        papers, raw_file = fetch.main()
        raw_count = len(papers)
        logger.info(f'Fetched {raw_count} papers')
        
        # Step 2: 规则过滤
        logger.info('\n>>> Step 2: Filtering papers')
        import filter
        filtered_papers, processed_file = filter.main(raw_file)
        filtered_count = len(filtered_papers)
        logger.info(f'Filtered to {filtered_count} papers')
        
        # Step 3: LLM评分
        logger.info('\n>>> Step 3: Ranking papers with LLM')
        import rank
        top_papers = rank.main(processed_file)
        ranked_count = len([p for p in json.load(open(processed_file)) if 'scores' in p])
        logger.info(f'Selected top {len(top_papers)} papers')
        
        # Step 4: 生成报告
        logger.info('\n>>> Step 4: Generating report')
        import report
        stats = {
            'raw_count': raw_count,
            'filtered_count': filtered_count,
            'ranked_count': ranked_count
        }
        report_file = report.generate_report(top_papers, stats, SCRIPT_DIR, WORKSPACE_DIR)
        
        # Step 5: 更新状态
        logger.info('\n>>> Step 5: Updating state')
        total_top_ids = update_state(top_papers, SCRIPT_DIR)
        
        # Step 6: 上传到飞书
        logger.info('\n>>> Step 6: Uploading to Feishu')
        import feishu
        stats['top_count'] = len(top_papers)
        feishu_result = feishu.upload_and_notify(report_file, stats)
        
        logger.info('\n' + '=' * 60)
        logger.info('Workflow completed successfully!')
        logger.info(f'Report: {report_file}')
        logger.info(f'Upload: {"✅" if feishu_result["upload_success"] else "❌"}')
        logger.info(f'Notification: {"✅" if feishu_result["notify_success"] else "❌"}')
        logger.info('=' * 60)
        
        return {
            'raw_count': raw_count,
            'filtered_count': filtered_count,
            'top_count': len(top_papers),
            'report_file': report_file,
            'total_historical_top': total_top_ids,
            'upload_success': feishu_result['upload_success'],
            'notify_success': feishu_result['notify_success']
        }
        
    except Exception as e:
        logger.error(f'Workflow failed: {e}', exc_info=True)
        error_log = LOG_DIR / 'error.log'
        with open(error_log, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.now().isoformat()} - WORKFLOW ERROR: {e}\n')
        
        if top_papers:
            logger.info(f'Note: {len(top_papers)} top papers selected but workflow failed.')
        
        raise


if __name__ == '__main__':
    main()
