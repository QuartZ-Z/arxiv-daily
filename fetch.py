#!/usr/bin/env python3
"""
Arxiv 论文抓取模块
使用用户验证成功的URL格式
"""
import yaml
import json
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
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

def load_private_config():
    """加载隐私配置文件"""
    private_config_path = SCRIPT_DIR / 'config_private.yaml'
    if private_config_path.exists():
        with open(private_config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

def build_query(config):
    """构建 arXiv 查询表达式"""
    keywords = config['keywords']
    categories = config['categories']
    
    # 构建关键词部分
    keyword_parts = []
    for kw in keywords:
        keyword_parts.append(f'(ti:"{kw}" OR abs:"{kw}")')
    
    keyword_query = ' OR '.join(keyword_parts)
    
    # 构建分类部分
    cat_parts = [f'cat:{cat}' for cat in categories]
    cat_query = ' OR '.join(cat_parts)
    
    # 组合查询
    full_query = f'({keyword_query}) AND ({cat_query})'
    return full_query

def encode_for_arxiv(query):
    """
    按照用户提供的成功格式编码:
    - 空格 -> +
    - 双引号 -> %22
    """
    # 首先对整个查询进行quote，保留括号和冒号
    encoded = urllib.parse.quote(query, safe='():')
    # 将%20（空格编码）替换为+
    encoded = encoded.replace('%20', '+')
    return encoded

def fetch_papers(query, max_results=500, start=0):
    """抓取论文元数据"""
    base_url = 'https://export.arxiv.org/api/query'
    
    # 加载隐私配置获取联系邮箱
    private_config = load_private_config()
    contact_email = private_config.get('arxiv', {}).get('contact_email', 'user@example.com')
    
    # 使用自定义编码
    encoded_query = encode_for_arxiv(query)
    
    url = f'{base_url}?search_query={encoded_query}&start={start}&max_results={min(100, max_results - start)}&sortBy=submittedDate&sortOrder=descending'
    
    logger.info(f'Fetching: start={start}, URL: {url[:150]}...')
    
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': f'OpenClaw-Arxiv-Agent ({contact_email})'
        }
    )
    
    # 指数退避重试
    for attempt in range(3):
        try:
            time.sleep(3)  # 限速：请求间隔 ≥ 3秒
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            wait_time = 3 ** attempt
            logger.warning(f'Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...')
            if attempt < 2:
                time.sleep(wait_time)
            else:
                logger.error(f'Failed to fetch after 3 attempts: {e}')
                raise
    
    return None

def parse_atom(xml_content):
    """解析 Atom XML 响应"""
    if not xml_content:
        return []
    
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'arxiv': 'http://arxiv.org/schemas/atom'
    }
    
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error(f'XML parse error: {e}')
        return []
    
    entries = []
    
    for entry in root.findall('atom:entry', ns):
        paper = {}
        
        id_elem = entry.find('atom:id', ns)
        if id_elem is not None:
            paper['arxiv_id'] = id_elem.text.split('/')[-1]
        
        title_elem = entry.find('atom:title', ns)
        if title_elem is not None:
            paper['title'] = title_elem.text.strip()
        
        authors = []
        for author in entry.findall('atom:author', ns):
            name_elem = author.find('atom:name', ns)
            if name_elem is not None:
                authors.append(name_elem.text)
        paper['authors'] = authors
        
        summary_elem = entry.find('atom:summary', ns)
        if summary_elem is not None:
            paper['abstract'] = summary_elem.text.strip()
        
        published_elem = entry.find('atom:published', ns)
        if published_elem is not None:
            paper['submittedDate'] = published_elem.text
        
        categories = []
        for cat in entry.findall('atom:category', ns):
            term = cat.get('term')
            if term:
                categories.append(term)
        paper['categories'] = categories
        
        entries.append(paper)
    
    return entries

def main():
    """主函数"""
    logger.info('=' * 50)
    logger.info('Starting arXiv fetch process')
    logger.info(f'Script directory: {SCRIPT_DIR}')
    logger.info('=' * 50)
    
    config = load_config()
    logger.info(f'Loaded config: {len(config["keywords"])} keywords, {len(config["categories"])} categories')
    
    query = build_query(config)
    logger.info(f'Raw query: {query[:150]}...')
    
    # 确保数据目录存在
    data_dir = SCRIPT_DIR / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = data_dir / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    state_path = data_dir / 'state.json'
    if state_path.exists():
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {'top_paper_ids': [], 'last_removed_ids': []}
    
    last_success_time = state.get('last_success_time', '')
    
    if last_success_time:
        logger.info(f'Last success time: {last_success_time}')
    else:
        last_success_time = (datetime.now() - timedelta(days=config['time_window_days'])).isoformat()
        logger.info(f'First run, using time window start: {last_success_time}')
    
    all_papers = []
    max_results = config['query_max_results']
    
    for start in range(0, max_results, 100):
        try:
            xml_content = fetch_papers(query, max_results, start)
            papers = parse_atom(xml_content)
            
            if not papers:
                logger.info('No more papers found')
                break
            
            all_papers.extend(papers)
            logger.info(f'Fetched {len(papers)} papers, total: {len(all_papers)}')
            
            if last_success_time:
                stop_fetching = False
                for p in papers:
                    if p.get('submittedDate', '') <= last_success_time:
                        logger.info(f'Reached last success time at {p.get("submittedDate")}')
                        stop_fetching = True
                        break
                if stop_fetching:
                    break
                
        except Exception as e:
            logger.error(f'Error fetching papers: {e}')
            error_log = LOG_DIR / 'error.log'
            with open(error_log, 'a', encoding='utf-8') as f:
                f.write(f'{datetime.now().isoformat()} - FETCH ERROR: {e}\n')
            break
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_file = raw_dir / f'papers_{timestamp}.json'
    with open(raw_file, 'w', encoding='utf-8') as f:
        json.dump(all_papers, f, ensure_ascii=False, indent=2)
    
    logger.info(f'Saved {len(all_papers)} papers to {raw_file}')
    
    state['last_fetch_time'] = datetime.now().isoformat()
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    
    logger.info('Fetch process completed')
    return all_papers, str(raw_file)

if __name__ == '__main__':
    main()
