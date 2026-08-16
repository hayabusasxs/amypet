# modules/delete.py
import os
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Union, Optional, Tuple
from tqdm import tqdm

from . import utils
import config

logger = logging.getLogger(__name__)

def delete_files_in_directory(dir_path: Path, confirm: bool = True, keep_nifti: bool = False) -> Dict[str, int]:
    """
    删除指定目录下除了文件夹以外的所有文件，可选择保留.nii.gz文件
    
    参数:
        dir_path: 目录路径
        confirm: 是否在删除前确认
        keep_nifti: 是否保留.nii.gz文件
        
    返回:
        删除结果统计
    """
    result = {
        'directory': str(dir_path),
        'files_found': 0,
        'files_deleted': 0
    }
    
    if not dir_path.exists() or not dir_path.is_dir():
        logger.warning(f"⚠️ 目录不存在: {dir_path}")
        return result
    
    # 获取目录下所有文件（不包括文件夹）
    if keep_nifti:
        files_to_delete = [f for f in dir_path.iterdir() if f.is_file() and not f.name.endswith('.nii.gz')]
        logger.info(f"将保留所有.nii.gz文件")
    else:
        files_to_delete = [f for f in dir_path.iterdir() if f.is_file()]
    
    result['files_found'] = len(files_to_delete)
    
    if not files_to_delete:
        logger.info(f"ℹ️ 目录 {dir_path} 中没有{'符合条件的' if keep_nifti else ''}文件需要删除")
        return result
    
    # 列出要删除的文件
    logger.info(f"🔍 在 {dir_path} 中找到 {len(files_to_delete)} 个{'(除.nii.gz外的)' if keep_nifti else ''}文件:")
    for file in files_to_delete[:10]:  # 只显示前10个
        logger.info(f"  - {file.name}")
    if len(files_to_delete) > 10:
        logger.info(f"  ... 还有 {len(files_to_delete) - 10} 个文件")
    
    # 确认删除
    if confirm:
        response = input(f"确认删除 {dir_path} 中的 {len(files_to_delete)} 个{'(除.nii.gz外的)' if keep_nifti else ''}文件吗? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            logger.info("❌ 取消删除操作")
            return result
    
    # 执行删除
    for file in files_to_delete:
        try:
            file.unlink()
            result['files_deleted'] += 1
        except Exception as e:
            logger.error(f"❌ 删除文件 {file} 时出错: {e}")
    
    logger.info(f"🗑️ 已从 {dir_path} 中删除 {result['files_deleted']}/{result['files_found']} 个{'(除.nii.gz外的)' if keep_nifti else ''}文件")
    return result

def delete_patient_files(patient_id: str, modality: str = 'both', confirm: bool = True, keep_nifti: bool = False) -> Dict[str, Dict]:
    """
    删除单个患者目录下除了文件夹以外的所有文件，可选择保留.nii.gz文件
    
    参数:
        patient_id: 患者ID
        modality: 处理模态，可选'mr', 'pet', 'both'
        confirm: 是否在删除前确认
        keep_nifti: 是否保留.nii.gz文件
        
    返回:
        删除结果字典
    """
    patient_id = utils.format_patient_id(patient_id)
    result = {
        'id': patient_id,
        'mr': None,
        'pet': None
    }
    
    # 删除MR目录下的文件
    if modality in ['mr', 'both']:
        mr_dir = config.MR_DIR / patient_id
        if mr_dir.exists():
            result['mr'] = delete_files_in_directory(mr_dir, confirm, keep_nifti)
        else:
            logger.warning(f"⚠️ 患者MR目录不存在: {mr_dir}")
    
    # 删除PET目录下的文件
    if modality in ['pet', 'both']:
        pet_dir = config.PET_DIR / patient_id
        if pet_dir.exists():
            result['pet'] = delete_files_in_directory(pet_dir, confirm, keep_nifti)
        else:
            logger.warning(f"⚠️ 患者PET目录不存在: {pet_dir}")
    
    logger.info(f"🧹 患者 {patient_id} 文件删除完成")
    return result

def delete_files_from_patient_ids(
    patient_ids: List[str],
    modality: str = 'both',
    confirm: bool = True,
    keep_nifti: bool = False
) -> Dict[str, Dict]:
    """
    批量删除指定ID列表患者目录下除了文件夹以外的所有文件，可选择保留.nii.gz文件
    
    参数:
        patient_ids: 患者ID列表
        modality: 处理模态，可选'mr', 'pet', 'both'
        confirm: 是否在删除前确认
        keep_nifti: 是否保留.nii.gz文件
        
    返回:
        包含每个患者删除结果的字典
    """
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    # 如果要删除多个患者的文件，先统一确认
    if len(formatted_ids) > 1 and confirm:
        logger.info(f"准备删除 {len(formatted_ids)} 个患者的{'(除.nii.gz外的)' if keep_nifti else ''}文件:")
        for pid in formatted_ids[:10]:
            logger.info(f"  - 患者 {pid}")
        if len(formatted_ids) > 10:
            logger.info(f"  ... 还有 {len(formatted_ids) - 10} 个患者")
        
        response = input(f"确认删除这些患者目录中的{'(除.nii.gz外的)' if keep_nifti else ''}文件吗? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            logger.info("❌ 取消删除操作")
            return {}
        
        # 已经确认，后续操作不再单独确认
        confirm = False
    
    results = {}
    
    # 处理每个患者
    for pid in tqdm(formatted_ids, desc="文件删除进度"):
        try:
            result = delete_patient_files(pid, modality, confirm, keep_nifti)
            results[pid] = result
        except Exception as e:
            logger.error(f"❌ 删除患者 {pid} 文件时出错: {e}")
            results[pid] = {
                'id': pid,
                'error': str(e)
            }
    
    # 统计结果
    mr_deleted_total = 0
    pet_deleted_total = 0
    mr_patients = 0
    pet_patients = 0
    
    for r in results.values():
        if 'mr' in r and r['mr']:
            mr_deleted_total += r['mr'].get('files_deleted', 0)
            if r['mr'].get('files_deleted', 0) > 0:
                mr_patients += 1
        
        if 'pet' in r and r['pet']:
            pet_deleted_total += r['pet'].get('files_deleted', 0)
            if r['pet'].get('files_deleted', 0) > 0:
                pet_patients += 1
    
    total = len(results)
    nifti_msg = "（保留.nii.gz文件）" if keep_nifti else ""
    
    if modality == 'mr':
        logger.info(f"🎉 MR文件删除完成{nifti_msg}，总计: {total}个患者，删除成功: {mr_patients}个患者，共删除: {mr_deleted_total}个文件")
    elif modality == 'pet':
        logger.info(f"🎉 PET文件删除完成{nifti_msg}，总计: {total}个患者，删除成功: {pet_patients}个患者，共删除: {pet_deleted_total}个文件")
    else:
        logger.info(f"🎉 文件删除完成{nifti_msg}，总计: {total}个患者，MR删除: {mr_patients}个患者/{mr_deleted_total}个文件，PET删除: {pet_patients}个患者/{pet_deleted_total}个文件")
    
    return results

def delete_files_from_range_str(
    range_str: str,
    modality: str = 'both',
    confirm: bool = True,
    keep_nifti: bool = False
) -> Dict[str, Dict]:
    """
    从范围字符串批量删除患者目录下除了文件夹以外的所有文件，可选择保留.nii.gz文件
    
    参数:
        range_str: 患者范围字符串，如"1-5,7,9-11"
        modality: 处理模态，可选'mr', 'pet', 'both'
        confirm: 是否在删除前确认
        keep_nifti: 是否保留.nii.gz文件
        
    返回:
        包含每个患者删除结果的字典
    """
    patient_ids = utils.parse_patient_range(range_str)
    return delete_files_from_patient_ids(patient_ids, modality, confirm, keep_nifti) 