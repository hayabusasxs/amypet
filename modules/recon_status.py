#!/usr/bin/env python3
# modules/recon_status.py

import os
import logging
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime

from . import utils
import config

logger = logging.getLogger(__name__)

def extract_recon_status(subject_id: str) -> Dict[str, Any]:
    """
    提取指定患者的recon-all状态信息
    
    参数:
        subject_id: 患者ID
        
    返回:
        包含以下键的字典：
        - subject_id: 患者ID
        - version: FreeSurfer版本
        - start_date: recon-all开始日期
        - start_time: recon-all开始时间
        - runtime_hours: recon-all运行时间（小时）
        如果无法提取信息，返回的字典中对应值为None
    """
    subject_id = utils.format_patient_id(subject_id)
    result = {
        'subject_id': subject_id,
        'version': None,
        'start_date': None,
        'start_time': None,
        'runtime_hours': None
    }
    
    # 构建recon-all.done文件路径
    done_file = Path(config.RECON_DIR) / subject_id / 'scripts' / 'recon-all.done'
    
    # 检查文件是否存在
    if not done_file.exists():
        logger.warning(f"⚠️ recon-all.done文件不存在: {done_file}")
        return result
    
    try:
        # 读取文件内容
        with open(done_file, 'r') as f:
            content = f.readlines()
        
        # 提取信息
        for line in content:
            # 提取开始时间
            if line.startswith('START_TIME'):
                start_datetime = line.replace('START_TIME', '').strip()
                # 解析日期和时间
                # 格式：Sat Apr 5 05:49:23 CST 2025
                date_match = re.search(r'(\w+)\s+(\w+)\s+(\d+)', start_datetime)
                time_match = re.search(r'(\d+:\d+:\d+)', start_datetime)
                if date_match and time_match:
                    # 提取日期部分
                    weekday, month, day = date_match.groups()
                    result['start_date'] = f"{month} {day}"
                    # 提取时间部分
                    result['start_time'] = time_match.group(1)
            
            # 提取运行时间
            elif line.startswith('RUNTIME_HOURS'):
                runtime = line.replace('RUNTIME_HOURS', '').strip()
                try:
                    result['runtime_hours'] = float(runtime)
                except ValueError:
                    logger.error(f"❌ 无法解析运行时间: {runtime}")
            
            # 提取FreeSurfer版本
            elif line.startswith('VERSION'):
                version_line = line.replace('VERSION', '').strip()
                # 提取版本号，格式：7.4.1 (freesurfer-macOS-darwin_x86_64-7.4.1-20230614-7eb8460)
                version_match = re.search(r'(\d+\.\d+\.\d+)', version_line)
                if version_match:
                    result['version'] = version_match.group(1)
    
    except Exception as e:
        logger.error(f"❌ 提取recon-all状态信息时出错: {e}")
    
    return result

def save_recon_status(status_info: Dict[str, Any], fs_version: str = None) -> bool:
    """
    将recon-all状态信息保存到CSV文件
    
    参数:
        status_info: 包含状态信息的字典
        fs_version: FreeSurfer版本，用于确定保存路径
        
    返回:
        成功返回True，失败返回False
    """
    if not status_info:
        logger.error("❌ 没有提供状态信息")
        return False
    
    # 提取的版本用于显示在CSV中
    extracted_version = status_info.get('version')
    
    # 使用config中的FS_VERSION作为保存路径的版本
    # 这确保文件始终保存在正确的目录中，而不依赖于从文件中提取的版本
    path_version = config.FS_VERSION
    
    # 构建保存路径
    csv_dir = Path(config.ROOT_DIR) / 'data' / f'sheet_{path_version}'
    csv_file = csv_dir / 'recon_status.csv'
    
    # 确保目录存在
    os.makedirs(csv_dir, exist_ok=True)
    
    # 准备待写入的数据
    row_data = {
        '受试者id': status_info['subject_id'],
        'freesurfer版本': extracted_version,
        'recon_all开始日期': status_info['start_date'],
        'recon_all开始时间': status_info['start_time'],
        'recon_all耗时': status_info['runtime_hours']
    }
    
    # 检查文件是否存在
    file_exists = csv_file.exists()
    
    try:
        # 如果文件存在，首先检查是否有重复记录
        if file_exists:
            with open(csv_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 检查是否有相同的受试者ID和开始日期时间
                    if (row['受试者id'] == row_data['受试者id'] and 
                        row['recon_all开始日期'] == row_data['recon_all开始日期'] and
                        row['recon_all开始时间'] == row_data['recon_all开始时间']):
                        logger.info(f"⚠️ 已存在相同记录，拒绝写入: {row_data['受试者id']}")
                        return False
        
        # 写入CSV文件
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['受试者id', 'freesurfer版本', 'recon_all开始日期', 'recon_all开始时间', 'recon_all耗时']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 如果文件不存在或为空，写入表头
            if not file_exists or os.path.getsize(csv_file) == 0:
                writer.writeheader()
            
            # 写入数据
            writer.writerow(row_data)
        
        logger.info(f"✅ 已保存recon-all状态信息到: {csv_file}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 保存recon-all状态信息时出错: {e}")
        return False

def process_subject_recon_status(subject_id: str) -> Dict[str, Any]:
    """
    处理单个受试者的recon-all状态信息
    
    参数:
        subject_id: 患者ID
        
    返回:
        包含处理结果的字典
    """
    result = {
        'subject_id': subject_id,
        'success': False,
        'message': ''
    }
    
    try:
        # 提取状态信息
        status_info = extract_recon_status(subject_id)
        
        # 检查是否成功提取到关键信息 - 只要求开始日期和时间
        if not status_info.get('start_date') or not status_info.get('start_time'):
            message = f"未能提取到recon-all开始时间信息: {subject_id}"
            logger.warning(f"⚠️ {message}")
            result['message'] = message
            return result
        
        # 如果未能提取到版本信息，使用配置文件中的版本
        if not status_info.get('version'):
            logger.warning(f"⚠️ 未能从文件提取FreeSurfer版本信息，使用配置文件中的版本: {config.FS_VERSION}")
            status_info['version'] = config.FS_VERSION
        
        # 保存状态信息
        if save_recon_status(status_info):
            result['success'] = True
            result['message'] = f"成功处理并保存recon-all状态信息: {subject_id}"
            logger.info(f"✅ {result['message']}")
        else:
            result['message'] = f"保存recon-all状态信息失败: {subject_id}"
            logger.warning(f"⚠️ {result['message']}")
            
    except Exception as e:
        result['message'] = f"处理recon-all状态信息时出错: {e}"
        logger.error(f"❌ {result['message']}")
    
    return result

def process_subjects_recon_status(subject_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    处理多个受试者的recon-all状态信息
    
    参数:
        subject_ids: 患者ID列表
        
    返回:
        包含每个受试者处理结果的字典
    """
    results = {}
    
    for subject_id in subject_ids:
        formatted_id = utils.format_patient_id(subject_id)
        results[formatted_id] = process_subject_recon_status(formatted_id)
    
    # 打印总结
    success_count = sum(1 for r in results.values() if r['success'])
    logger.info(f"📊 处理完成: {success_count}/{len(results)} 个受试者成功")
    
    return results 