"""
PVC SUVR Calculator Module - PVC校正数据的SUVR计算模块

## 📋 功能说明
本模块直接读取mri_gtmpvc生成的gtm.stats.dat文件来计算SUVR值。
与suvr_calculator.py不同，本模块直接读取dat文件而非使用mri_stats命令。

## 📁 输入要求
1. GTM统计文件: gtm.stats.dat (由mri_gtmpvc生成)
2. 文件位置: {SUBJECTS_DIR}/{subject_id}/pet_pvc/{variant}/gtmpvc_psf{psf}.output/gtm.stats.dat

## 🔄 处理流程
1. 读取gtm.stats.dat文件
2. 根据FreeSurfer标签将ROI分组到感兴趣区域
3. 计算每个区域的加权平均PVC uptake值
4. 计算SUVR值
5. 生成结果文件并更新CSV汇总

## 📤 输出结果
- 结果保存在 data/sheet_8.0.0/pvc_results/psf_{psf}/ 目录中
- 生成与suvr_calculator.py相似的CSV文件，但不包含腐蚀白质相关列
"""

import os
import logging
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any
import concurrent.futures
from tqdm import tqdm
import re

from . import utils
import config

logger = logging.getLogger(__name__)

# 常量定义
PVC_RESULTS_BASE_DIR = Path(config.SHEET_DIR) / 'pvc_results'
PSF_VALUES = [2, 3, 4, 5, 6]  # 支持的PSF值
CSV_EXTENSION = '.csv'
TXT_EXTENSION = '.txt'

# 区域标签映射（来自mask_processor.py的MASK_REGIONS）
MASK_REGIONS = {
    'frontal': [1003, 1012, 1014, 1018, 1019, 1020, 1027, 1028, 1032, 
                2003, 2012, 2014, 2018, 2019, 2020, 2027, 2028, 2032],
    'cingulate': [1002, 1010, 1023, 1026, 2002, 2010, 2023, 2026],
    'parietal': [1008, 1025, 1029, 1031, 2008, 2025, 2029, 2031],
    'temporal': [1009, 1015, 1030, 2009, 2015, 2030],
    'cerebellumgm': [8, 47],
    'wholecerebellum': [7, 8, 46, 47],
    'brainstem': [16],
    'subcorticalwm': [2, 41]
}

# 合并所有靶区标签
COMPOSITE_LABELS = (
    MASK_REGIONS['frontal'] + 
    MASK_REGIONS['cingulate'] + 
    MASK_REGIONS['parietal'] + 
    MASK_REGIONS['temporal']
)

# 默认SUVR阈值
DEFAULT_THRESHOLDS = {
    'wholecerebellum': 1.11,
    'composite': 0.78
}

# CSV文件列定义（PVC版本，去掉腐蚀白质相关列）
# 注意：_Count列实际存储的是各区域的加权平均PVC uptake值，而非体素数
PVC_CSV_COLUMNS = [
    "Subject", "vTag1", "vTag2", "vTag3",
    "Composite_Count", "Cingulate_Count", "Frontal_Count", "Parietal_Count", "Temporal_Count",
    "CerebellumGM_Ref", "Brainstem_Ref", "WholeCerebellum_Ref", "SubcorticalWM_Ref", "Composite_Ref",
    "CerebellumGM_SUVR", "Brainstem_SUVR", "WholeCerebellum_SUVR", "SubcorticalWM_SUVR", "Composite_SUVR",
    "WholeCerebellum_Status", "Composite_Status",
    "Cingulate_WholeCerebellum_SUVR", "Frontal_WholeCerebellum_SUVR", 
    "Parietal_WholeCerebellum_SUVR", "Temporal_WholeCerebellum_SUVR"
]


def parse_gtm_stats_file(gtm_stats_path: Path) -> Optional[Dict[int, Dict[str, float]]]:
    """
    解析gtm.stats.dat文件
    
    参数:
        gtm_stats_path: GTM统计文件路径
        
    返回:
        包含ROI统计的字典: {roi_index: {'nvoxels': float, 'pvc_uptake': float}}
        失败返回None
    """
    if not gtm_stats_path.exists():
        logger.error(f"❌ GTM统计文件不存在: {gtm_stats_path}")
        return None
        
    try:
        roi_stats = {}
        
        with open(gtm_stats_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                # 解析行: 行号 ROI_ID ROI_名称 组织类型 体素数量 方差减少因子 PVC_uptake 残差方差
                parts = line.split()
                if len(parts) < 8:
                    logger.warning(f"⚠️ GTM文件第{line_num}行格式异常，跳过: {line}")
                    continue
                    
                try:
                    row_num = int(parts[0])
                    roi_index = int(parts[1])
                    roi_name = parts[2]
                    tissue_type = parts[3]
                    nvoxels = float(parts[4])
                    variance_reduction = float(parts[5])
                    pvc_uptake = float(parts[6])
                    residual_variance = float(parts[7])
                    
                    roi_stats[roi_index] = {
                        'roi_name': roi_name,
                        'tissue_type': tissue_type,
                        'nvoxels': nvoxels,
                        'variance_reduction': variance_reduction,
                        'pvc_uptake': pvc_uptake,
                        'residual_variance': residual_variance
                    }
                    
                except (ValueError, IndexError) as e:
                    logger.warning(f"⚠️ GTM文件第{line_num}行数据解析失败，跳过: {line}")
                    continue
        
        logger.info(f"✅ 成功解析GTM统计文件: {gtm_stats_path}, 共{len(roi_stats)}个ROI")
        return roi_stats
        
    except Exception as e:
        logger.error(f"❌ 解析GTM统计文件失败: {gtm_stats_path}, 错误: {e}")
        return None


def calculate_region_weighted_mean(roi_stats: Dict[int, Dict[str, float]], 
                                 region_labels: List[int]) -> Tuple[Optional[float], int]:
    """
    计算区域的加权平均PVC uptake值
    
    参数:
        roi_stats: ROI统计字典
        region_labels: 区域包含的标签列表
        
    返回:
        (加权平均值, 总体素数)，如果无法计算则返回(None, 0)
    """
    total_weighted_value = 0.0
    total_voxels = 0
    
    for label in region_labels:
        if label in roi_stats:
            voxels = roi_stats[label]['nvoxels']
            pvc_value = roi_stats[label]['pvc_uptake']
            
            if voxels > 0:  # 确保体素数大于0
                total_weighted_value += pvc_value * voxels
                total_voxels += voxels
    
    if total_voxels > 0:
        weighted_mean = total_weighted_value / total_voxels
        return weighted_mean, int(total_voxels)
    else:
        return None, 0


def calculate_pvc_suvr_for_variant(subject_id: str, variant_tag: str, psf_value: int) -> Dict[str, Any]:
    """
    为特定受试者、变体和PSF值计算PVC SUVR
    
    参数:
        subject_id: 受试者ID
        variant_tag: PET变体标识  
        psf_value: PSF值
        
    返回:
        包含计算结果的字典
    """
    subject_id = utils.format_patient_id(subject_id)
    
    # 构建GTM统计文件路径
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    gtm_stats_path = subject_dir / 'pet_pvc' / variant_tag / f'gtmpvc_psf{psf_value}.output' / 'gtm.stats.dat'
    
    result = {
        'success': False,
        'subject_id': subject_id,
        'variant_tag': variant_tag,
        'psf_value': psf_value,
        'target_means': {},
        'reference_means': {},
        'suvr_values': {},
        'judgments': {},
        'error': None
    }
    
    # 检查GTM统计文件是否存在
    if not gtm_stats_path.exists():
        error_msg = f"GTM统计文件不存在: {gtm_stats_path}"
        logger.error(f"❌ {error_msg}")
        result['error'] = error_msg
        return result
    
    # 解析GTM统计文件
    roi_stats = parse_gtm_stats_file(gtm_stats_path)
    if roi_stats is None:
        error_msg = f"解析GTM统计文件失败: {gtm_stats_path}"
        logger.error(f"❌ {error_msg}")
        result['error'] = error_msg
        return result
    
    logger.info(f"🔄 开始计算PVC SUVR: 受试者={subject_id}, 变体={variant_tag}, PSF={psf_value}")
    
    # 计算靶区平均值
    target_regions = {
        'composite': COMPOSITE_LABELS,
        'frontal': MASK_REGIONS['frontal'],
        'cingulate': MASK_REGIONS['cingulate'], 
        'parietal': MASK_REGIONS['parietal'],
        'temporal': MASK_REGIONS['temporal']
    }
    
    for region_name, labels in target_regions.items():
        weighted_mean, total_voxels = calculate_region_weighted_mean(roi_stats, labels)
        if weighted_mean is not None:
            result['target_means'][region_name] = weighted_mean
            result['target_means'][f'{region_name}_voxels'] = total_voxels  # 存储体素数但不用于CSV
            logger.debug(f"靶区 {region_name}: 加权平均PVC uptake={weighted_mean:.4f}, 体素数={total_voxels}")
        else:
            logger.warning(f"⚠️ 无法计算靶区 {region_name} 的加权平均PVC uptake")
    
    # 计算参考区平均值
    reference_regions = {
        'cerebellumgm': MASK_REGIONS['cerebellumgm'],
        'wholecerebellum': MASK_REGIONS['wholecerebellum'],
        'brainstem': MASK_REGIONS['brainstem'],
        'subcorticalwm': MASK_REGIONS['subcorticalwm']
    }
    
    for region_name, labels in reference_regions.items():
        weighted_mean, total_voxels = calculate_region_weighted_mean(roi_stats, labels)
        if weighted_mean is not None:
            result['reference_means'][region_name] = weighted_mean
            logger.debug(f"参考区 {region_name}: 平均值={weighted_mean:.4f}, 体素数={total_voxels}")
        else:
            logger.warning(f"⚠️ 无法计算参考区 {region_name} 的平均值")
    
    # 检查是否获得了复合靶区的值（必需）
    composite_mean = result['target_means'].get('composite')
    if composite_mean is None:
        error_msg = f"无法计算关键的复合靶区平均值"
        logger.error(f"❌ {error_msg}")
        result['error'] = error_msg
        return result
    
    # 计算复合参考区平均值（包括wholecerebellum + brainstem + subcorticalwm）
    composite_ref_labels = (MASK_REGIONS['wholecerebellum'] + 
                           MASK_REGIONS['brainstem'] + 
                           MASK_REGIONS['subcorticalwm'])
    composite_ref_mean, _ = calculate_region_weighted_mean(roi_stats, composite_ref_labels)
    if composite_ref_mean is not None:
        result['reference_means']['composite'] = composite_ref_mean
        logger.debug(f"复合参考区: 平均值={composite_ref_mean:.4f}")
    
    # 计算SUVR值
    for ref_name, ref_mean in result['reference_means'].items():
        if ref_mean is not None and ref_mean > 1e-9:  # 避免除零
            suvr = composite_mean / ref_mean
            result['suvr_values'][ref_name] = suvr
            logger.debug(f"SUVR ({ref_name}): {suvr:.4f}")
        else:
            logger.warning(f"⚠️ 参考区 {ref_name} 的值无效，无法计算SUVR")
    
    # 计算各脑区相对于全小脑的SUVR
    wholecerebellum_mean = result['reference_means'].get('wholecerebellum')
    if wholecerebellum_mean is not None and wholecerebellum_mean > 1e-9:
        region_names = ['frontal', 'cingulate', 'parietal', 'temporal']
        for region_name in region_names:
            region_mean = result['target_means'].get(region_name)
            if region_mean is not None:
                region_suvr = region_mean / wholecerebellum_mean
                result['suvr_values'][f'{region_name}_wholecerebellum'] = region_suvr
                logger.debug(f"{region_name} 相对全小脑SUVR: {region_suvr:.4f}")
    
    # 进行阳性判断
    for region_name, threshold in DEFAULT_THRESHOLDS.items():
        suvr_value = result['suvr_values'].get(region_name)
        if suvr_value is not None:
            result['judgments'][region_name] = "+" if suvr_value >= threshold else "-"
        else:
            result['judgments'][region_name] = ""
    
    result['success'] = True
    logger.info(f"✅ PVC SUVR计算完成: 受试者={subject_id}, 变体={variant_tag}, PSF={psf_value}")
    
    return result


def get_psf_output_dir(psf_value: int) -> Path:
    """
    获取特定PSF值的输出目录路径
    
    参数:
        psf_value: PSF值
        
    返回:
        PSF特定的输出目录路径
    """
    psf_dir = PVC_RESULTS_BASE_DIR / f'psf_{psf_value}'
    psf_dir.mkdir(parents=True, exist_ok=True)
    return psf_dir


def extract_pure_variant_tag(full_variant_name: str) -> str:
    """
    从完整的变体目录名中提取纯粹的变体标识
    
    例如:
        '001_pet-1-1-1' -> '-1-1-1'
        '002_pet-zte' -> '-zte'
        '003_pet-2-3-5' -> '-2-3-5'
    
    参数:
        full_variant_name: 完整的变体目录名
        
    返回:
        纯粹的变体标识
    """
    # 查找第一个 '-' 的位置，这通常是变体标识的开始
    if '_pet-' in full_variant_name:
        # 提取 '_pet-' 之后的部分
        variant_part = full_variant_name.split('_pet-', 1)[1]
        return f'-{variant_part}'
    elif '_pet' in full_variant_name and full_variant_name.endswith('_pet'):
        # 处理标准pet的情况（如果存在）
        return 'standard'
    else:
        # 如果格式不符合预期，记录警告并返回原始名称
        logger.warning(f"⚠️ 无法从 '{full_variant_name}' 提取变体标识，使用原始名称")
        return full_variant_name


def _prepare_pvc_csv_row(result: Dict[str, Any]) -> List[str]:
    """
    根据PVC SUVR计算结果准备CSV行数据
    
    参数:
        result: PVC SUVR计算结果字典
        
    返回:
        CSV行数据列表
    """
    row = []
    
    # Subject
    row.append(result['subject_id'])
    
    # vTag1, vTag2, vTag3 - 解析变体标识
    variant_tag = result.get('variant_tag', '')
    
    # 使用extract_pure_variant_tag函数提取纯粹的变体标识
    pure_variant_tag = extract_pure_variant_tag(variant_tag)
    
    # 移除开头的'-'来提取标签部分
    tag_part = pure_variant_tag
    if tag_part.startswith('-') and len(tag_part) > 1:
        tag_part = tag_part[1:]  # 移除开头的'-'
    elif tag_part == 'standard':
        tag_part = ''  # 标准变体用空字符串表示
    
    # 分割标签
    if tag_part:
        tag_parts = tag_part.split('-')
    else:
        tag_parts = ['']  # 空标签处理为标准变体
    
    v1 = tag_parts[0] if len(tag_parts) > 0 else ''
    v2 = tag_parts[1] if len(tag_parts) > 1 else ''
    v3 = tag_parts[2] if len(tag_parts) > 2 else ''
    row.extend([v1, v2, v3])
    
    # Target counts - 实际存储加权平均PVC uptake值
    target_means = result.get('target_means', {})
    row.append(f"{target_means.get('composite', ''):.4f}" if target_means.get('composite') else '')
    row.append(f"{target_means.get('cingulate', ''):.4f}" if target_means.get('cingulate') else '')
    row.append(f"{target_means.get('frontal', ''):.4f}" if target_means.get('frontal') else '')
    row.append(f"{target_means.get('parietal', ''):.4f}" if target_means.get('parietal') else '')
    row.append(f"{target_means.get('temporal', ''):.4f}" if target_means.get('temporal') else '')
    
    # Reference means
    reference_means = result.get('reference_means', {})
    row.append(f"{reference_means.get('cerebellumgm', ''):.4f}" if reference_means.get('cerebellumgm') else '')
    row.append(f"{reference_means.get('brainstem', ''):.4f}" if reference_means.get('brainstem') else '')
    row.append(f"{reference_means.get('wholecerebellum', ''):.4f}" if reference_means.get('wholecerebellum') else '')
    row.append(f"{reference_means.get('subcorticalwm', ''):.4f}" if reference_means.get('subcorticalwm') else '')
    row.append(f"{reference_means.get('composite', ''):.4f}" if reference_means.get('composite') else '')
    
    # SUVR values
    suvr_values = result.get('suvr_values', {})
    row.append(f"{suvr_values.get('cerebellumgm', ''):.4f}" if suvr_values.get('cerebellumgm') else '')
    row.append(f"{suvr_values.get('brainstem', ''):.4f}" if suvr_values.get('brainstem') else '')
    row.append(f"{suvr_values.get('wholecerebellum', ''):.4f}" if suvr_values.get('wholecerebellum') else '')
    row.append(f"{suvr_values.get('subcorticalwm', ''):.4f}" if suvr_values.get('subcorticalwm') else '')
    row.append(f"{suvr_values.get('composite', ''):.4f}" if suvr_values.get('composite') else '')
    
    # Judgments
    judgments = result.get('judgments', {})
    row.append(judgments.get('wholecerebellum', ''))
    row.append(judgments.get('composite', ''))
    
    # Regional SUVR
    row.append(f"{suvr_values.get('cingulate_wholecerebellum', ''):.4f}" if suvr_values.get('cingulate_wholecerebellum') else '')
    row.append(f"{suvr_values.get('frontal_wholecerebellum', ''):.4f}" if suvr_values.get('frontal_wholecerebellum') else '')
    row.append(f"{suvr_values.get('parietal_wholecerebellum', ''):.4f}" if suvr_values.get('parietal_wholecerebellum') else '')
    row.append(f"{suvr_values.get('temporal_wholecerebellum', ''):.4f}" if suvr_values.get('temporal_wholecerebellum') else '')
    
    return row


def update_pvc_csv_files(result: Dict[str, Any]) -> bool:
    """
    更新PVC SUVR的CSV汇总文件
    支持三种模式：
    1. 按变体汇总 (all_patients_pvc_suvr-<variant>.csv)
    2. 按患者分类 ({patient_id}_suvr_summary.csv)  
    3. 全体汇总 (all_patients_pvc_suvr.csv)
    
    参数:
        result: PVC SUVR计算结果
        
    返回:
        更新成功返回True
    """
    if not result.get('success'):
        logger.warning("⚠️ 跳过更新CSV文件，因为SUVR计算未成功")
        return False
    
    psf_value = result['psf_value']
    subject_id = result['subject_id']
    variant_tag = result['variant_tag']
    
    overall_success = True
    
    try:
        # 获取PSF特定的输出目录
        psf_dir = get_psf_output_dir(psf_value)
        
        # --- 模式1: 按变体汇总 (all_patients_pvc_suvr-<processed_variant_tag>.csv) ---
        # 从完整的变体目录名中提取纯粹的变体标识
        pure_variant_tag = extract_pure_variant_tag(variant_tag)
        
        file_variant_suffix = pure_variant_tag if pure_variant_tag else "standard"
        if file_variant_suffix.startswith('-') and len(file_variant_suffix) > 1:
            file_variant_suffix = file_variant_suffix[1:]
        elif file_variant_suffix == "-":
            file_variant_suffix = "dash"
        
        # 处理特殊字符，确保文件名合法
        file_variant_suffix = file_variant_suffix.replace('/', '_').replace('\\', '_')
        
        per_variant_csv_filename = f"all_patients_pvc_suvr-{file_variant_suffix}{CSV_EXTENSION}"
        per_variant_csv_file = psf_dir / per_variant_csv_filename
        try:
            _update_single_csv_file(per_variant_csv_file, result, include_header_check=True)
            logger.info(f"✅ (模式1) PSF={psf_value}, 受试者={subject_id}, 变体={file_variant_suffix} -> {per_variant_csv_filename}")
        except Exception as e:
            logger.error(f"❌ (模式1) 更新按变体分类的CSV文件失败: {e}")
            overall_success = False
        
        # --- 模式2: 按患者分类 ({patient_id}_suvr_summary.csv) ---
        per_patient_csv_filename = f"{subject_id}_suvr_summary{CSV_EXTENSION}"
        per_patient_csv_file = psf_dir / per_patient_csv_filename
        try:
            _update_single_csv_file(per_patient_csv_file, result, include_header_check=True)
            logger.info(f"✅ (模式2) PSF={psf_value}, 受试者={subject_id} -> {per_patient_csv_filename}")
        except Exception as e:
            logger.error(f"❌ (模式2) 更新按患者分类的CSV文件失败: {e}")
            overall_success = False
        
        # --- 模式3: 全体汇总 (all_patients_pvc_suvr.csv) ---
        all_patients_csv_filename = f"all_patients_pvc_suvr{CSV_EXTENSION}"
        all_patients_csv_file = psf_dir / all_patients_csv_filename
        try:
            _update_single_csv_file(all_patients_csv_file, result, include_header_check=True)
            logger.info(f"✅ (模式3) PSF={psf_value}, 受试者={subject_id} -> {all_patients_csv_filename}")
        except Exception as e:
            logger.error(f"❌ (模式3) 更新全体汇总CSV文件失败: {e}")
            overall_success = False
        
        if overall_success:
            logger.info(f"🎉 CSV文件更新完成: PSF={psf_value}, 受试者={subject_id}, 变体={pure_variant_tag}")
        else:
            logger.warning(f"⚠️ CSV文件部分更新失败: PSF={psf_value}, 受试者={subject_id}, 变体={pure_variant_tag}")
            
        return overall_success
        
    except Exception as e:
        logger.error(f"❌ 更新CSV文件时发生意外错误: {e}")
        return False


def _update_single_csv_file(csv_file: Path, result: Dict[str, Any], include_header_check: bool = True) -> None:
    """
    更新单个CSV文件
    
    参数:
        csv_file: CSV文件路径
        result: 计算结果
        include_header_check: 是否包含表头检查
    """
    # 检查是否需要写入表头
    write_header = not csv_file.exists()
    
    # 准备数据行
    row_data = _prepare_pvc_csv_row(result)
    
    # 写入CSV文件
    with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        
        if write_header:
            writer.writerow(PVC_CSV_COLUMNS)
        
        writer.writerow(row_data)


def find_pvc_variants(subject_id: str) -> List[Tuple[str, List[int]]]:
    """
    查找受试者的PVC变体和对应的PSF值
    
    参数:
        subject_id: 受试者ID
        
    返回:
        [(变体名称, [PSF值列表])] 的列表
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    pvc_dir = subject_dir / 'pet_pvc'
    
    if not pvc_dir.exists():
        logger.warning(f"⚠️ PVC目录不存在: {pvc_dir}")
        return []
    
    variants_info = []
    
    for variant_dir in pvc_dir.iterdir():
        if variant_dir.is_dir():
            variant_name = variant_dir.name
            available_psfs = []
            
            # 检查每个PSF值对应的输出目录
            for psf_value in PSF_VALUES:
                gtm_output_dir = variant_dir / f'gtmpvc_psf{psf_value}.output'
                gtm_stats_file = gtm_output_dir / 'gtm.stats.dat'
                
                if gtm_stats_file.exists():
                    available_psfs.append(psf_value)
            
            if available_psfs:
                variants_info.append((variant_name, available_psfs))
                logger.info(f"找到变体: {variant_name}, 可用PSF: {available_psfs}")
            else:
                logger.warning(f"⚠️ 变体 {variant_name} 没有可用的GTM统计文件")
    
    return variants_info


def process_subject_pvc_suvr(subject_id: str) -> Dict[str, Any]:
    """
    处理单个受试者的所有PVC SUVR计算
    
    参数:
        subject_id: 受试者ID
        
    返回:
        包含所有变体和PSF组合结果的字典
    """
    subject_id = utils.format_patient_id(subject_id)
    
    result = {
        'subject_id': subject_id,
        'success': False,
        'variants_processed': 0,
        'total_calculations': 0,
        'successful_calculations': 0,
        'variant_results': {},
        'errors': []
    }
    
    try:
        logger.info(f"🔄 开始处理受试者 {subject_id} 的PVC SUVR...")
        
        # 查找PVC变体
        variants_info = find_pvc_variants(subject_id)
        if not variants_info:
            error_msg = f"受试者 {subject_id} 未找到任何PVC变体"
            logger.error(f"❌ {error_msg}")
            result['errors'].append(error_msg)
            return result
        
        # 处理每个变体和PSF组合
        for variant_name, psf_list in variants_info:
            result['variants_processed'] += 1
            result['variant_results'][variant_name] = {}
            
            for psf_value in psf_list:
                result['total_calculations'] += 1
                
                # 计算PVC SUVR
                pvc_result = calculate_pvc_suvr_for_variant(subject_id, variant_name, psf_value)
                result['variant_results'][variant_name][f'psf_{psf_value}'] = pvc_result
                
                if pvc_result['success']:
                    result['successful_calculations'] += 1
                    
                    # 更新CSV文件
                    csv_success = update_pvc_csv_files(pvc_result)
                    if not csv_success:
                        logger.warning(f"⚠️ CSV更新失败: 变体={variant_name}, PSF={psf_value}")
                else:
                    error_msg = f"变体 {variant_name} PSF {psf_value} 计算失败: {pvc_result.get('error', '未知错误')}"
                    result['errors'].append(error_msg)
        
        # 判断整体成功状态
        result['success'] = (result['successful_calculations'] > 0 and 
                           result['successful_calculations'] == result['total_calculations'])
        
        if result['success']:
            logger.info(f"✅ 受试者 {subject_id} PVC SUVR计算完全成功: "
                       f"{result['successful_calculations']}/{result['total_calculations']} 个计算")
        else:
            logger.warning(f"⚠️ 受试者 {subject_id} PVC SUVR计算部分成功: "
                          f"{result['successful_calculations']}/{result['total_calculations']} 个计算")
        
    except Exception as e:
        error_msg = f"处理受试者 {subject_id} 时发生异常: {e}"
        logger.error(f"❌ {error_msg}")
        result['errors'].append(error_msg)
    
    return result


def process_subjects_pvc_suvr_parallel(patient_ids: List[str], max_workers: int = 4) -> Dict[str, Any]:
    """
    并行处理多个受试者的PVC SUVR计算
    
    参数:
        patient_ids: 患者ID列表
        max_workers: 最大并行处理数
        
    返回:
        所有受试者的处理结果
    """
    if not patient_ids:
        logger.warning("⚠️ 未提供患者ID列表")
        return {}
    
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    logger.info(f"🚀 开始并行PVC SUVR计算: {len(formatted_ids)} 个受试者")
    
    results = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_patient = {
            executor.submit(process_subject_pvc_suvr, patient_id): patient_id
            for patient_id in formatted_ids
        }
        
        # 使用tqdm显示进度
        with tqdm(total=len(formatted_ids), desc="PVC SUVR计算进度", unit="受试者") as pbar:
            for future in concurrent.futures.as_completed(future_to_patient):
                patient_id = future_to_patient[future]
                try:
                    result = future.result()
                    results[patient_id] = result
                    
                    # 更新进度条描述
                    status = "✅" if result['success'] else "❌"
                    calc_info = f"{result.get('successful_calculations', 0)}/{result.get('total_calculations', 0)}"
                    pbar.set_postfix(当前=f"{status} {patient_id} ({calc_info})")
                    pbar.update(1)
                    
                except Exception as e:
                    error_msg = f"处理受试者 {patient_id} 时发生异常: {e}"
                    logger.error(f"❌ {error_msg}")
                    results[patient_id] = {
                        'subject_id': patient_id,
                        'success': False,
                        'errors': [error_msg]
                    }
                    pbar.set_postfix(当前=f"❌ {patient_id}")
                    pbar.update(1)
    
    # 统计总体结果
    _log_pvc_suvr_summary(results)
    
    return results


def _log_pvc_suvr_summary(results: Dict[str, Any]) -> None:
    """
    记录PVC SUVR处理结果摘要
    
    参数:
        results: 所有受试者的处理结果
    """
    if not results:
        logger.info("PVC SUVR计算完成，但没有处理任何数据。")
        return
    
    total_subjects = len(results)
    successful_subjects = sum(1 for r in results.values() if r.get('success', False))
    total_calculations = sum(r.get('total_calculations', 0) for r in results.values())
    successful_calculations = sum(r.get('successful_calculations', 0) for r in results.values())
    
    logger.info("🎉 PVC SUVR批量处理完成统计:")
    logger.info(f"  - 受试者成功率: {successful_subjects}/{total_subjects} ({successful_subjects/total_subjects*100:.1f}%)")
    
    if total_calculations > 0:
        logger.info(f"  - 计算任务成功率: {successful_calculations}/{total_calculations} ({successful_calculations/total_calculations*100:.1f}%)")
    else:
        logger.info("  - 计算任务: 0/0 (未找到任何可处理的任务)")
    
    # 记录失败的受试者
    failed_subjects = [pid for pid, r in results.items() if not r.get('success', False)]
    if failed_subjects:
        logger.warning("⚠️ 以下受试者处理失败:")
        for pid in failed_subjects[:10]:  # 最多显示10个
            logger.warning(f"    - {pid}")
        if len(failed_subjects) > 10:
            logger.warning(f"    ... 以及其他 {len(failed_subjects) - 10} 个受试者")


def calculate_pvc_suvr_for_patients(patient_ids: List[str], max_workers: int = 4) -> Dict[str, Any]:
    """
    为患者列表计算PVC SUVR（主入口函数）
    
    参数:
        patient_ids: 患者ID列表
        max_workers: 最大并行处理数
        
    返回:
        处理结果字典
    """
    logger.info(f"🎯 启动PVC SUVR计算模块，处理 {len(patient_ids)} 个受试者")
    
    # 创建输出目录结构
    PVC_RESULTS_BASE_DIR.mkdir(parents=True, exist_ok=True)
    for psf_value in PSF_VALUES:
        get_psf_output_dir(psf_value)  # 确保PSF目录存在
    
    # 执行并行处理
    results = process_subjects_pvc_suvr_parallel(patient_ids, max_workers)
    
    logger.info(f"🏁 PVC SUVR计算模块完成")
    
    return results


def calculate_pvc_suvr_for_range(start_subj: int, end_subj: int, max_workers: int = 4) -> Dict[str, Any]:
    """
    为指定范围内的受试者计算PVC SUVR
    
    参数:
        start_subj: 起始受试者编号
        end_subj: 结束受试者编号  
        max_workers: 最大并行处理数
        
    返回:
        处理结果字典
    """
    if start_subj > end_subj:
        logger.error(f"❌ 无效的受试者范围: {start_subj}-{end_subj}")
        return {}
    
    # 生成患者ID列表
    patient_ids = [str(i) for i in range(start_subj, end_subj + 1)]
    logger.info(f"开始处理患者范围 {start_subj}-{end_subj}，共 {len(patient_ids)} 个患者")
    
    return calculate_pvc_suvr_for_patients(patient_ids, max_workers)
