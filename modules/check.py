#!/usr/bin/env python3
# modules/check.py

"""
检查FreeSurfer重建、PET配准和掩膜结果的工具

提供以下功能:
- 分割和区域检查 (segmentation and parcellation check)
- 配准检查 (registration check)
- 掩膜检查 (mask check)
- 全面检查 (all check)
"""

import os
import logging
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional, Union

from . import utils

# 初始化日志
logger = logging.getLogger(__name__)


def contains_chinese(path_str: str) -> bool:
    """
    检查路径是否包含中文字符
    
    参数:
        path_str: 待检查的路径字符串
        
    返回:
        如果路径包含中文字符则返回True，否则返回False
    """
    pattern = re.compile(r'[\u4e00-\u9fa5]')
    return bool(pattern.search(path_str))


def verify_no_chinese_in_paths(paths: List[str]) -> bool:
    """
    验证一组路径中不包含中文字符
    
    参数:
        paths: 待验证的路径列表
        
    返回:
        如果所有路径都不包含中文字符则返回True，否则返回False
    """
    for path in paths:
        if contains_chinese(path):
            logger.error(f"{utils.ERROR_EMOJI} 路径 '{path}' 包含中文字符，freeview不支持中文路径")
            return False
    return True


def check_segmentation(subject_id: str, recon_dir: Union[str, Path]) -> None:
    """
    检查FreeSurfer的分割和区域划分结果
    
    参数:
        subject_id: 受试者ID
        recon_dir: FreeSurfer重建目录
    """
    _check_segmentation(subject_id, Path(recon_dir))


def check_masks(subject_id: str, recon_dir: Union[str, Path]) -> None:
    """
    检查掩膜生成结果
    
    参数:
        subject_id: 受试者ID
        recon_dir: FreeSurfer重建目录
    """
    _check_mask(subject_id, Path(recon_dir))


def check_all(subject_id: str, recon_dir: Union[str, Path]) -> None:
    """
    进行全面检查，包括分割、配准和掩膜检查以及PET影像
    
    参数:
        subject_id: 受试者ID
        recon_dir: FreeSurfer重建目录
    """
    _check_all(subject_id, Path(recon_dir))


def check_results(subject_id: str, 
                  check_type: str, 
                  recon_dir: Union[str, Path]):
    """
    根据检查类型，调用不同的检查函数
    
    参数:
        subject_id (str): 受试者ID
        check_type (str): 检查类型 ('sc', 'rc', 'mc', 'ac')
        recon_dir (Union[str, Path]): FreeSurfer重建目录
    """
    recon_dir = Path(recon_dir)
    subject_id = utils.format_patient_id(subject_id)
        
    logger.info(f"✅ 开始对受试者 {subject_id} 进行 {check_type} 检查...")
    
    if check_type == 'sc':
        _check_segmentation(subject_id, recon_dir)
    elif check_type == 'rc':
        _check_registration(subject_id, recon_dir)
    elif check_type == 'mc':
        _check_mask(subject_id, recon_dir)
    elif check_type == 'ac':
        _check_all(subject_id, recon_dir)
    else:
        logger.error(f"❌ 未知的检查类型: {check_type}")
        logger.info("   可用的检查类型: 'sc' (分割检查), 'rc' (配准检查), 'mc' (掩膜检查), 'ac' (全面检查)")
        
def _check_segmentation(subject_id: str, recon_dir: Path):
    """
    检查FreeSurfer的分割和区域划分结果
    
    参数:
        subject_id: 受试者ID
        recon_dir: FreeSurfer重建目录
    """
    # 格式化受试者ID并构建路径
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(recon_dir) / subject_id
    
    t1_path = subject_dir / "mri" / "T1.mgz"
    brain_path = subject_dir / "mri" / "brain.mgz"
    aparc_aseg_path = subject_dir / "mri" / "aparc+aseg.mgz"
    
    # 验证文件存在
    for path in [t1_path, brain_path, aparc_aseg_path]:
        if not path.exists():
            logger.error(f"{utils.ERROR_EMOJI} 文件不存在: {path}")
            return
    
    # 验证路径不包含中文
    paths = [str(t1_path), str(brain_path), str(aparc_aseg_path)]
    if not verify_no_chinese_in_paths(paths):
        return
    
    # 构建freeview命令
    cmd = [
        "freeview", "-v",
        str(t1_path),
        f"{str(brain_path)}:opacity=.45:colormap=grayscale",
        f"{str(aparc_aseg_path)}:opacity=.5"
    ]
    
    # 运行命令
    logger.info(f"{utils.SUCCESS_EMOJI} 启动分割和区域划分检查...")
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"{utils.SUCCESS_EMOJI} 分割和区域划分检查完成")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 启动Freeview时出错: {e}")

def _check_registration(subject_id: str, recon_dir: Path):
    """
    检查配准结果 (PET to MR)
    - 我们使用已经配准好的NIfTI文件来检查
    """
    logger.info(f"✅ 开始对受试者 {subject_id} 进行 rc 检查...")
    
    # 构建T1.mgz的路径
    t1_path = recon_dir / subject_id / "mri" / "T1.mgz"
    if not t1_path.exists():
        logger.error(f"❌ T1.mgz 文件不存在: {t1_path}")
        return

    # 指定要检查的变体列表
    target_variants = ['1-1-1', '2-2-2', '3-3-3']
    pet_variants_dir = recon_dir / subject_id / "pet"
    registered_pet_files = []

    logger.info(f"🔎 将只检查指定的变体: {', '.join(target_variants)}")
    for variant in target_variants:
        pet_file = pet_variants_dir / f"{subject_id}_pet-{variant}" / "registrated_pet.nii.gz"
        if pet_file.exists():
            registered_pet_files.append(pet_file)
        else:
            logger.warning(f"⚠️ 未找到变体 '{variant}' 的配准文件: {pet_file}")

    if not registered_pet_files:
        logger.error(f"❌ 未找到任何指定的配准过的PET文件。")
        return
            
    # 构建freeview命令
    # freeview -v <T1.mgz> <registrated_pet_1.nii.gz> <registrated_pet_2.nii.gz> ...
    cmd = ['freeview', '-v', str(t1_path)]
    for pet_file in registered_pet_files:
        cmd.append(f"{str(pet_file)}:colormap=gecolor:opacity=.5")
        
    logger.info(f"🔧 执行命令: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"✅ Freeview已启动，请检查配reigstration结果。")
    except FileNotFoundError:
        logger.error(f"❌ 命令 'freeview' 未找到。请确保FreeSurfer环境已正确设置。")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 启动Freeview时出错: {e}")

def _check_mask(subject_id: str, recon_dir: Path):
    """
    检查掩膜生成结果
    
    参数:
        subject_id: 受试者ID
        recon_dir: FreeSurfer重建目录
    """
    # 格式化受试者ID并构建路径
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(recon_dir) / subject_id
    
    t1_path = subject_dir / "mri" / "T1.mgz"
    aparc_aseg_path = subject_dir / "mri" / "aparc+aseg.mgz"
    mask_dir = subject_dir / "mask"
    
    # 验证基础文件存在
    for path in [t1_path, aparc_aseg_path, mask_dir]:
        if not path.exists():
            logger.error(f"{utils.ERROR_EMOJI} 文件/目录不存在: {path}")
            return
    
    # 构建掩膜文件路径列表
    mask_files = [
        mask_dir / "cingulate_mask.nii.gz",
        mask_dir / "frontal_mask.nii.gz",
        mask_dir / "parietal_mask.nii.gz",
        mask_dir / "composite.nii.gz",
        mask_dir / "ref_brainstem.nii.gz",
        mask_dir / "ref_cerebellumgm.nii.gz",
        mask_dir / "ref_subcorticalwm.nii.gz",
        mask_dir / "ref_subcorticalwm_fsm8.nii.gz",
        mask_dir / "ref_subcorticalwm_fsm8_thr07.nii.gz",
        mask_dir / "ref_subcorticalwm_erode1.nii.gz",
        mask_dir / "ref_subcorticalwm_erode2.nii.gz",
        mask_dir / "ref_composite.nii.gz",
        mask_dir / "ref_composite_fsm8_thr07.nii.gz",
        mask_dir / "ref_composite_e1.nii.gz",
        mask_dir / "ref_composite_e2.nii.gz"
    ]
    
    # 验证掩膜文件存在
    existing_masks = []
    for mask_file in mask_files:
        if mask_file.exists():
            existing_masks.append(str(mask_file))
        else:
            logger.warning(f"{utils.WARNING_EMOJI} 掩膜文件不存在: {mask_file}")
    
    if not existing_masks:
        logger.error(f"{utils.ERROR_EMOJI} 未找到任何掩膜文件")
        return
    
    # 验证路径不包含中文
    paths = [str(t1_path), str(aparc_aseg_path)] + existing_masks
    if not verify_no_chinese_in_paths(paths):
        return
    
    # 构建freeview命令
    cmd = ["freeview", "-v", str(t1_path), f"{str(aparc_aseg_path)}:opacity=.5"]
    
    # 添加所有存在的掩膜文件
    for mask_path in existing_masks:
        opacity = ".3" if "composite.nii.gz" in mask_path else ".4"
        cmd.append(f"{mask_path}:opacity={opacity}")
    
    # 运行命令
    logger.info(f"{utils.SUCCESS_EMOJI} 启动掩膜检查...")
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"{utils.SUCCESS_EMOJI} 掩膜检查完成")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 启动Freeview时出错: {e}")

def _check_all(subject_id: str, recon_dir: Path):
    """
    全面检查，包括分割、配准和掩膜
    """
    # 格式化受试者ID并构建路径
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(recon_dir) / subject_id
    
    t1_path = subject_dir / "mri" / "T1.mgz"
    aparc_aseg_path = subject_dir / "mri" / "aparc+aseg.mgz"
    mask_dir = subject_dir / "mask"
    
    # 验证基础文件存在
    for path in [t1_path, aparc_aseg_path, mask_dir]:
        if not path.exists():
            logger.error(f"{utils.ERROR_EMOJI} 文件/目录不存在: {path}")
            return
    
    # 构建掩膜文件路径列表
    mask_files = [
        mask_dir / "cingulate_mask.nii.gz",
        mask_dir / "frontal_mask.nii.gz",
        mask_dir / "parietal_mask.nii.gz",
        mask_dir / "composite.nii.gz",
        mask_dir / "ref_brainstem.nii.gz",
        mask_dir / "ref_cerebellumgm.nii.gz",
        mask_dir / "ref_subcorticalwm.nii.gz",
        mask_dir / "ref_subcorticalwm_fsm8.nii.gz",
        mask_dir / "ref_subcorticalwm_fsm8_thr07.nii.gz",
        mask_dir / "ref_subcorticalwm_erode1.nii.gz",
        mask_dir / "ref_subcorticalwm_erode2.nii.gz",
        mask_dir / "ref_composite.nii.gz",
        mask_dir / "ref_composite_fsm8_thr07.nii.gz",
        mask_dir / "ref_composite_e1.nii.gz",
        mask_dir / "ref_composite_e2.nii.gz"
    ]
    
    # 验证掩膜文件存在
    existing_masks = []
    for mask_file in mask_files:
        if mask_file.exists():
            existing_masks.append(str(mask_file))
        else:
            logger.warning(f"{utils.WARNING_EMOJI} 掩膜文件不存在: {mask_file}")
    
    if not existing_masks:
        logger.error(f"{utils.ERROR_EMOJI} 未找到任何掩膜文件")
        return
    
    # 验证路径不包含中文
    paths = [str(t1_path), str(aparc_aseg_path), str(mask_dir)] + existing_masks
    if not verify_no_chinese_in_paths(paths):
        return
    
    # 构建freeview命令
    cmd = ['freeview', '-v']
    
    # 添加所有存在的掩膜文件
    for mask_path in existing_masks:
        opacity = ".3" if "composite.nii.gz" in mask_path else ".4"
        cmd.append(f"{mask_path}:opacity={opacity}")
    
    # 运行命令
    logger.info(f"{utils.SUCCESS_EMOJI} 启动全面检查...")
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"{utils.SUCCESS_EMOJI} 全面检查完成")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 启动Freeview时出错: {e}") 