# modules/directory_renamer.py
import os
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Callable
import concurrent.futures
from tqdm import tqdm
from functools import partial

from . import utils
import config

logger = logging.getLogger(__name__)

# 常量定义
ID_PATTERNS = [
    r'(?:^|[^0-9])([0-9]{1,3})(?:_|\s|$|[^0-9])',  # 提取1-3位数字
    r'(?:id|ID|Id)[_\-\s]*([0-9]{1,3})',  # 匹配 id123 或 ID-123
    r'(?:subject|Subject|SUBJECT)[_\-\s]*([0-9]{1,3})',  # 匹配 Subject-123
    r'(?:patient|Patient|PATIENT)[_\-\s]*([0-9]{1,3})',  # 匹配 Patient-123
    r'(?:pt|PT|Pt)[_\-\s]*([0-9]{1,3})'  # 匹配 PT-123
]

MODALITY_PATTERNS = {
    'pet': ['pet', 'fdg'],
    'mr': ['mr', 'mri', 't1']
}

def is_modality_folder(folder_path: Path, modality: str) -> bool:
    """
    检查文件夹是否为指定模态的数据文件夹
    
    参数:
        folder_path: 文件夹路径
        modality: 模态类型，'pet'或'mr'
        
    返回:
        如果文件夹匹配指定模态则返回True，否则返回False
    """
    folder_name = folder_path.name.lower()
    patterns = MODALITY_PATTERNS.get(modality.lower(), [])
    return any(pattern in folder_name for pattern in patterns)

def detect_patient_id_from_folder(folder_path: Path) -> Optional[str]:
    """
    从文件夹名称或内容中检测患者ID
    
    参数:
        folder_path: 文件夹路径
        
    返回:
        检测到的患者ID（3位数格式）或None
    """
    folder_name = folder_path.name
    
    # 尝试从文件夹名称中直接提取ID
    for pattern in ID_PATTERNS:
        match = re.search(pattern, folder_name)
        if match:
            # 确保ID是3位数字
            patient_id = utils.format_patient_id(match.group(1))
            logger.debug(f"从文件夹名称中检测到患者ID: {patient_id}")
            return patient_id
    
    # 如果从文件夹名称中无法提取ID，尝试从DICOM文件名中提取
    for item in folder_path.iterdir():
        if item.is_file() and item.suffix.lower() in ['.dcm', '.ima']:
            match = re.search(ID_PATTERNS[0], item.name)
            if match:
                patient_id = utils.format_patient_id(match.group(1))
                logger.debug(f"从文件名中检测到患者ID: {patient_id}")
                return patient_id
            break
    
    # 无法检测到ID
    logger.warning(f"⚠️ 无法从文件夹中检测到患者ID: {folder_path}")
    return None

def scan_patient_folders(base_dir: Path, modality: str) -> Dict[str, List[Path]]:
    """
    扫描指定目录下的所有患者文件夹
    
    参数:
        base_dir: 基础目录路径
        modality: 模态类型，'pet'或'mr'
        
    返回:
        字典，键为患者ID，值为该患者的文件夹列表
    """
    # 初始化结果字典
    patient_folders = {}
    
    # 确保目录存在
    if not base_dir.exists() or not base_dir.is_dir():
        logger.error(f"❌ 目录不存在: {base_dir}")
        return patient_folders
        
    # 遍历目录下的所有文件夹
    for folder in base_dir.iterdir():
        if not folder.is_dir():
            continue
            
        # 检查是否已经是标准命名格式 (例如: 001_pet)
        std_pattern = re.compile(r'^(\d{3})_(pet|mr)$', re.IGNORECASE)
        match = std_pattern.match(folder.name)
        
        if match:
            # 已经是标准格式，直接添加
            patient_id = match.group(1)
            if patient_id not in patient_folders:
                patient_folders[patient_id] = []
            patient_folders[patient_id].append(folder)
        else:
            # 尝试检测患者ID
            patient_id = detect_patient_id_from_folder(folder)
            
            if patient_id and is_modality_folder(folder, modality):
                if patient_id not in patient_folders:
                    patient_folders[patient_id] = []
                patient_folders[patient_id].append(folder)
    
    return patient_folders

def rename_folder(folder_path: Path, new_name: str) -> Tuple[bool, Path]:
    """
    重命名文件夹
    
    参数:
        folder_path: 原文件夹路径
        new_name: 新的文件夹名称
        
    返回:
        (成功标志, 新的文件夹路径)
    """
    try:
        new_path = folder_path.parent / new_name
        
        # 检查目标路径是否已存在
        if new_path.exists():
            # 如果已存在并且是相同的文件夹，则不需要操作
            if folder_path.samefile(new_path):
                logger.info(f"✅ 文件夹已经命名正确: {new_path}")
                return True, new_path
                
            # 否则需要合并内容
            logger.warning(f"⚠️ 目标路径已存在，将合并内容: {new_path}")
            
            # 复制所有内容
            for item in folder_path.iterdir():
                target = new_path / item.name
                if not target.exists():
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
            
            # 删除原文件夹
            shutil.rmtree(folder_path)
        else:
            # 直接重命名
            folder_path.rename(new_path)
            
        logger.info(f"✅ 文件夹重命名成功: {folder_path} -> {new_path}")
        return True, new_path
    except Exception as e:
        logger.error(f"❌ 重命名文件夹失败: {folder_path} -> {new_name}, 错误: {e}")
        return False, folder_path

def process_patient_folders(patient_id: str, folders: List[Path], modality: str) -> bool:
    """
    处理单个患者的文件夹
    
    参数:
        patient_id: 患者ID
        folders: 该患者的文件夹列表
        modality: 模态类型，'pet'或'mr'
        
    返回:
        处理成功返回True，否则返回False
    """
    # 标准文件夹名称
    standard_name = f"{patient_id}_{modality}"
    
    # 检查是否已经有标准命名的文件夹
    for folder in folders:
        if folder.name.lower() == standard_name.lower():
            logger.info(f"✅ 患者 {patient_id} 已有标准命名文件夹: {folder}")
            return True
    
    # 如果没有标准命名的文件夹，重命名第一个文件夹
    success, _ = rename_folder(folders[0], standard_name)
    
    return success

def process_modality_directory(base_dir: Path, patient_ids: List[str], modality: str, max_workers: int) -> Tuple[Dict[str, bool], Set[str]]:
    """处理指定模态的目录"""
    results = {}
    skipped_patients = set()
    tasks = []  # 用于存储待处理的任务 (patient_id, old_folder_path, new_folder_name)
    
    logger.info(f"🔍 扫描{modality.upper()}目录: {base_dir}")
    
    for patient_id in patient_ids:
        patient_dir = base_dir / patient_id
        if not patient_dir.exists() or not patient_dir.is_dir():
            logger.warning(f"⚠️ 患者 {patient_id} 的目录不存在: {patient_dir}")
            continue
            
        # 检查患者目录下是否有非标准命名的目录需要重命名
        standard_folder_pattern = re.compile(rf"^{patient_id}_{modality}(-[\w\-\s]+)?$", re.IGNORECASE) # 匹配 001_pet 或 001_pet-variant
        
        # 收集所有非标准命名的文件夹
        non_standard_folders = []
        # 收集已存在的标准文件夹名称，用于避免重命名冲突和重复处理
        existing_standard_names = set()

        for subfolder in patient_dir.iterdir():
            if subfolder.is_dir():
                if standard_folder_pattern.match(subfolder.name):
                    logger.info(f"✅ 患者 {patient_id} 已有标准命名的{modality.upper()}文件夹: {subfolder.name}")
                    results[subfolder.name] = True # 标记已存在的标准文件夹为成功
                    existing_standard_names.add(subfolder.name.lower())
                else:
                    non_standard_folders.append(subfolder)
        
        if non_standard_folders:
            for subfolder_to_rename in non_standard_folders:
                # 为MR模态使用简单的标准命名，为PET保留变体标识
                if modality.lower() == 'mr':
                    # MR模态使用简单的标准命名格式：{patient_id}_mr
                    new_folder_name = f"{patient_id}_{modality}"
                else:
                    # PET模态保留变体标识
                    original_folder_name = subfolder_to_rename.name
                    variant_tag_match = re.match(r"([^_]+)", original_folder_name)
                    
                    if variant_tag_match:
                        variant_tag = variant_tag_match.group(1)
                        new_folder_name = f"{patient_id}_{modality}-{variant_tag}"
                    else:
                        # 如果无法提取变体标识，使用基本命名
                        logger.warning(f"⚠️ 无法从文件夹 {original_folder_name} (属于患者 {patient_id}) 提取变体标识，使用基本命名。")
                        new_folder_name = f"{patient_id}_{modality}"

                if new_folder_name.lower() in existing_standard_names:
                    original_folder_name = subfolder_to_rename.name
                    logger.info(f"ℹ️ 患者 {patient_id} 的目标文件夹 {new_folder_name} 已存在或与现有标准文件夹冲突，跳过重命名 {original_folder_name}")
                    results[original_folder_name] = False # 标记为处理失败或跳过
                    skipped_patients.add(patient_id) # 可以选择是否将此情况视为跳过
                    continue
                
                tasks.append({
                    "patient_id": patient_id,
                    "old_folder_path": subfolder_to_rename,
                    "new_name": new_folder_name,
                    "modality": modality
                })
                existing_standard_names.add(new_folder_name.lower()) # 添加到已处理集合，避免重复任务
        elif not any(standard_folder_pattern.match(sf.name) for sf in patient_dir.iterdir() if sf.is_dir()):
             # 如果没有非标准文件夹，也没有任何标准文件夹，记录日志
            logger.warning(f"⚠️ 患者 {patient_id} 的{modality.upper()}目录下未找到任何可处理的文件夹。")


    logger.info(f"✅ 找到 {len(tasks)} 个{modality.upper()}文件夹需要重命名")
    
    if not tasks:
        return results, skipped_patients
    
    with tqdm(total=len(tasks), desc=f"{modality.upper()}目录重命名进度") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task_info = {}
            for task in tasks:
                # process_patient_folders 需要能够处理单个文件夹的重命名
                # 传递 patient_id, [old_folder_path], modality, 和 new_name
                future = executor.submit(
                    rename_folder, # 直接调用 rename_folder
                    task["old_folder_path"],
                    task["new_name"]
                )
                future_to_task_info[future] = task

            for future in concurrent.futures.as_completed(future_to_task_info):
                task_info = future_to_task_info[future]
                patient_id = task_info["patient_id"]
                original_name = task_info["old_folder_path"].name
                new_name = task_info["new_name"]
                try:
                    success, _ = future.result() # rename_folder 返回 (bool, Path)
                    results[new_name] = success # 使用新名称作为键
                    if not success:
                        skipped_patients.add(patient_id)
                        logger.error(f"❌ 重命名文件夹 {original_name} 为 {new_name} 失败 (患者 {patient_id})")
                except Exception as e:
                    logger.error(f"❌ 处理患者 {patient_id} 的文件夹 {original_name} 为 {new_name} 时出错: {e}")
                    results[new_name] = False # 使用新名称标记失败
                    skipped_patients.add(patient_id)
                
                pbar.update(1)
    
    return results, skipped_patients

def rename_directory_for_ids(patient_ids: List[str], modality: str = 'both', max_workers: int = 4) -> Tuple[Dict[str, bool], Set[str]]:
    """重命名指定ID列表患者的数据目录"""
    # 将患者ID格式化为标准格式
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    results = {}
    skipped_patients = set()
    
    # 根据模态类型处理相应目录
    if modality in ['pet', 'both']:
        pet_results, pet_skipped = process_modality_directory(
            Path(config.PET_DIR),
            formatted_ids,
            'pet',
            max_workers
        )
        results.update(pet_results)
        skipped_patients.update(pet_skipped)
    
    if modality in ['mr', 'both']:
        mr_results, mr_skipped = process_modality_directory(
            Path(config.MR_DIR),
            formatted_ids,
            'mr',
            max_workers
        )
        results.update(mr_results)
        skipped_patients.update(mr_skipped)
    
    # 统计结果
    total = len(results)
    success_count = sum(1 for success in results.values() if success)
    
    logger.info(f"🎉 目录重命名完成，总计: {total}个，成功: {success_count}，失败: {total - success_count}")
    
    if skipped_patients:
        logger.warning(f"⚠️ 以下患者被跳过处理: {', '.join(sorted(skipped_patients))}")
    
    return results, skipped_patients