#!/usr/bin/env python3
"""
飞书上传模块 - 通过 Gateway HTTP API 调用 OpenClaw 工具
"""
import os
import json
import logging
import requests
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

# 加载隐私配置
def _load_private_config():
    """加载 config_private.yaml 中的隐私配置"""
    config_path = Path(__file__).parent / 'config_private.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

_private_config = _load_private_config()
_feishu_config = _private_config.get('feishu', {})

# 配置 - 从 config_private.yaml 读取
PARENT_NODE = _feishu_config.get('parent_node', '')
CHAT_ID = _feishu_config.get('chat_id', '')


def get_gateway_config():
    """获取 Gateway 配置"""
    gateway_url = os.environ.get('OpenClawGatewayUrl', 'http://127.0.0.1:18789')
    gateway_token = os.environ.get('OpenClawGatewayToken', '')
    return gateway_url, gateway_token


def invoke_tool(tool_name, args):
    """通过 Gateway HTTP API 调用工具
    
    Returns:
        dict: 原始响应结果，或 None 如果出错
    """
    gateway_url, gateway_token = get_gateway_config()
    
    headers = {
        'Authorization': f'Bearer {gateway_token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'tool': tool_name,
        'args': args
    }
    
    try:
        response = requests.post(
            f'{gateway_url}/tools/invoke',
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f'Tool invocation error: {e}')
        return None


def upload_report(report_file):
    """上传报告到飞书云盘 arxiv_daily 文件夹
    
    Args:
        report_file: 报告文件路径
    
    Returns:
        bool: 是否上传成功
    """
    logger.info('>>> Uploading report to Feishu Drive')
    
    abs_path = str(Path(report_file).resolve())
    logger.info(f'Report file: {abs_path}')
    logger.info(f'Target folder: arxiv_daily (parent_node: {PARENT_NODE})')
    
    result = invoke_tool('feishu_drive_file', {
        'action': 'upload',
        'file_path': abs_path,
        'parent_node': PARENT_NODE
    })
    
    # 判断是否成功 - 检查根级别 ok 字段
    if result and result.get('ok'):
        logger.info('✅ Upload successful')
        return True
    else:
        logger.error(f'❌ Upload failed: {result}')
        return False


def send_notification(report_file, stats):
    """发送飞书通知
    
    Args:
        report_file: 报告文件路径
        stats: 统计信息字典
    
    Returns:
        bool: 是否发送成功
    """
    logger.info('>>> Sending Feishu notification')
    
    from datetime import datetime
    today = datetime.now().strftime('%Y年%m月%d日')
    report_name = Path(report_file).name
    
    message = f"📚 arXiv 日报已完成 ({today})\n\n"
    message += f"✅ 抓取论文：{stats['raw_count']} 篇\n"
    message += f"✅ 过滤后：{stats['filtered_count']} 篇\n"
    message += f"✅ 推荐论文：{stats['top_count']} 篇\n\n"
    message += f"📄 报告已上传：{report_name}\n"
    message += f"👉 请前往云盘「arxiv_daily」文件夹查看"
    
    result = invoke_tool('message', {
        'action': 'send',
        'channel': 'feishu',
        'target': CHAT_ID,
        'message': message
    })
    
    # 判断是否成功 - 检查根级别 ok 字段
    if result and result.get('ok'):
        logger.info('✅ Notification sent')
        return True
    else:
        logger.error(f'⚠️ Notification failed: {result}')
        return False


def upload_and_notify(report_file, stats):
    """上传报告并发送通知
    
    Args:
        report_file: 报告文件路径
        stats: 统计信息字典
    
    Returns:
        dict: 上传和通知结果
    """
    upload_success = upload_report(report_file)
    notify_success = send_notification(report_file, stats)
    
    return {
        'upload_success': upload_success,
        'notify_success': notify_success
    }


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        upload_report(sys.argv[1])
    else:
        print("Usage: python feishu.py <report_file>")
