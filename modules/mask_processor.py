# modules/mask_processor.py
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, Callable, Set
import concurrent.futures
from tqdm import tqdm

from . import utils
import config

logger = logging.getLogger(__name__)

# 常量定义
NIFTI_EXTENSION = '.nii.gz'
MGZ_EXTENSION = '.mgz'
TXT_EXTENSION = '.txt'
DEFAULT_MASK_DIR = 'mask'

# 定义掩膜区域的标签
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

# 合并所有皮层区域的标签
COMPOSITE_LABELS = (
    MASK_REGIONS['frontal'] + 
    MASK_REGIONS['cingulate'] + 
    MASK_REGIONS['parietal'] + 
    MASK_REGIONS['temporal']
)

def _get_mask_dir(subject_id: str, output_dir: Optional[Path] = None) -> Path:
    """
    获取掩膜目录路径
    
    参数:
        subject_id: 受试者ID
        output_dir: 自定义输出目录
        
    返回:
        掩膜目录路径
    """
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    mask_dir = output_dir if output_dir is not None else subject_dir / DEFAULT_MASK_DIR
    return mask_dir

def _get_mask_paths(subject_id: str, mask_name: str, is_reference: bool = False, output_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """
    获取掩膜文件的MGZ和NIfTI路径
    
    参数:
        subject_id: 受试者ID
        mask_name: 掩膜名称
        is_reference: 是否为参考区域掩膜
        output_dir: 输出目录
        
    返回:
        (MGZ掩膜路径, NIfTI掩膜路径)
    """
    mask_dir = _get_mask_dir(subject_id, output_dir)
    
    # 根据掩膜类型确定文件名
    if is_reference:
        prefix = f"ref_{mask_name}"
    elif mask_name == "composite":
        # 复合掩膜特殊处理，不添加_mask后缀
        prefix = mask_name
    else:
        prefix = f"{mask_name}_mask"
    
    mask_mgz = mask_dir / f"{prefix}{MGZ_EXTENSION}"
    mask_nii = mask_dir / f"{prefix}{NIFTI_EXTENSION}"
    
    return mask_mgz, mask_nii

def create_mask(subject_id: str, mask_name: str, labels: List[int], is_reference: bool = False, output_dir: Optional[Path] = None) -> Tuple[bool, Optional[Path]]:
    """
    为指定区域创建二值掩膜
    
    参数:
        subject_id: 受试者ID
        mask_name: 掩膜名称
        labels: 要包含的FreeSurfer标签列表
        is_reference: 是否为参考区域掩膜
        output_dir: 输出目录，默认为 <SUBJECTS_DIR>/<subject_id>/mask
    
    返回:
        (成功标志, 生成的掩膜NIfTI文件路径)
    """
    subject_id = utils.format_patient_id(subject_id)
    
    # 参数验证
    if not labels:
        logger.error(f"❌ 未提供标签列表，无法创建{mask_name}掩膜")
        return False, None
    
    # 创建必要的目录
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    mask_dir = _get_mask_dir(subject_id, output_dir)
    mask_dir.mkdir(parents=True, exist_ok=True)
    
    # 检查FreeSurfer重建是否存在
    aparc_aseg = subject_dir / 'mri' / 'aparc+aseg.mgz'
    if not aparc_aseg.exists():
        logger.error(f"❌ 找不到分割文件: {aparc_aseg}")
        return False, None
    
    try:
        logger.info(f"🔄 创建{mask_name}掩膜...")
        
        # 获取掩膜文件路径
        mask_mgz, mask_nii = _get_mask_paths(subject_id, mask_name, is_reference, output_dir)
        
        # 构建mri_binarize命令
        cmd = [
            'mri_binarize', 
            '--i', str(aparc_aseg), 
            '--match'
        ]
        # 添加所有标签
        cmd.extend([str(label) for label in labels])
        # 添加输出文件
        cmd.extend(['--o', str(mask_mgz)])
        
        # 运行命令创建MGZ格式掩膜
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        # 转换为NIfTI格式
        cmd = ['mri_convert', str(mask_mgz), str(mask_nii)]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        logger.info(f"✅ {mask_name}掩膜创建完成: {mask_nii}")
        return True, mask_nii
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 创建{mask_name}掩膜命令执行失败: {e}")
        logger.error(f"错误输出: {e.stderr if hasattr(e, 'stderr') else '未知错误'}")
        return False, None
    except Exception as e:
        logger.error(f"❌ 创建{mask_name}掩膜失败: {e}")
        return False, None

def create_composite_mask(subject_id: str) -> Tuple[bool, Optional[Path]]:
    """
    创建合并所有皮层区域的复合掩膜
    
    参数:
        subject_id: 受试者ID
    
    返回:
        (成功标志, 生成的掩膜NIfTI文件路径)
    """
    logger.info(f"🔄 创建复合皮层掩膜 (包含 {len(COMPOSITE_LABELS)} 个标签)...")
    return create_mask(subject_id, "composite", COMPOSITE_LABELS, is_reference=False)

def calculate_mask_stats(subject_id: str, mask_file: Path) -> bool:
    """
    使用mri_segstats计算掩膜体积统计
    
    参数:
        subject_id: 受试者ID
        mask_file: 掩膜文件路径
        
    返回:
        成功标志
    """
    # 参数验证
    if not mask_file.exists():
        logger.error(f"❌ 掩膜文件不存在: {mask_file}")
        return False
        
    try:
        # 生成统计文件路径 (与掩膜同名，但扩展名为.txt)
        stats_file = mask_file.parent / f"{mask_file.stem}{TXT_EXTENSION}"
        
        # 运行mri_segstats命令
        cmd = [
            'mri_segstats', 
            '--seg', str(mask_file), 
            '--sum', str(stats_file)
        ]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        logger.info(f"✅ 已生成掩膜统计: {stats_file}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 生成掩膜统计命令执行失败: {e}")
        logger.error(f"错误输出: {e.stderr if hasattr(e, 'stderr') else '未知错误'}")
        return False
    except Exception as e:
        logger.error(f"❌ 生成掩膜统计失败: {e}")
        return False

def process_subcortical_wm(subject_id: str) -> Dict[str, Tuple[bool, Optional[Path]]]:
    """
    处理皮质下白质区域，包括平滑、腐蚀和体积统计
    
    参数:
        subject_id: 受试者ID
    
    返回:
        包含各处理步骤结果的字典
    """
    subject_id = utils.format_patient_id(subject_id)
    results = {}
    
    # 创建必要的目录
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    mask_dir = _get_mask_dir(subject_id)
    
    # 检查皮质下白质掩膜是否存在
    wm_mask = mask_dir / f"ref_subcorticalwm{NIFTI_EXTENSION}"
    if not wm_mask.exists():
        logger.error(f"❌ 找不到皮质下白质掩膜: {wm_mask}")
        return {'original': (False, None)}
    
    try:
        logger.info(f"🔄 处理皮质下白质区域...")
        
        # 1. 使用FSL进行平滑处理 (σ=3.4mm约等于FWHM=8mm)
        wm_fsm8 = mask_dir / f"ref_subcorticalwm_fsm8{NIFTI_EXTENSION}"
        cmd = [
            'fslmaths', 
            str(wm_mask), 
            '-s', '3.39729', 
            str(wm_fsm8)
        ]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        results['smoothed'] = (True, wm_fsm8)
        calculate_mask_stats(subject_id, wm_fsm8)
        
        # 2. 对平滑后的图像进行阈值处理(≥0.7)
        wm_thr07 = mask_dir / f"ref_subcorticalwm_fsm8_thr07{NIFTI_EXTENSION}"
        cmd = [
            'mri_binarize', 
            '--i', str(wm_fsm8), 
            '--min', '0.7', 
            '--o', str(wm_thr07)
        ]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        results['thr07'] = (True, wm_thr07)
        calculate_mask_stats(subject_id, wm_thr07)
        
        # 3. 生成不同侵蚀级别的白质区域
        for erode_level in [1, 2]:
            wm_erode = mask_dir / f"ref_subcorticalwm_erode{erode_level}{NIFTI_EXTENSION}"
            cmd = [
                'mri_convert', 
                str(wm_mask), 
                str(wm_erode), 
                '--erode-seg', str(erode_level)
            ]
            utils.run_freesurfer_command(cmd, subject_id=subject_id)
            results[f'erode{erode_level}'] = (True, wm_erode)
            calculate_mask_stats(subject_id, wm_erode)
        
        logger.info(f"✅ 皮质下白质处理完成")
        return results
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 皮质下白质处理命令执行失败: {e}")
        logger.error(f"错误输出: {e.stderr if hasattr(e, 'stderr') else '未知错误'}")
        return {'error': (False, None)}
    except Exception as e:
        logger.error(f"❌ 皮质下白质处理失败: {e}")
        return {'error': (False, None)}

def _check_required_files(files: List[Path]) -> bool:
    """
    检查所有必需的文件是否存在
    
    参数:
        files: 文件路径列表
        
    返回:
        所有文件都存在返回True，否则返回False
    """
    missing_files = [str(f) for f in files if not f.exists()]
    
    if missing_files:
        logger.error(f"❌ 找不到以下必需文件: {', '.join(missing_files)}")
        return False
    return True

def create_composite_reference(subject_id: str) -> Tuple[bool, Optional[Path]]:
    """
    创建复合参考掩膜
    
    参数:
        subject_id: 受试者ID
    
    返回:
        (成功标志, 生成的复合参考掩膜NIfTI文件路径)
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    mask_dir = _get_mask_dir(subject_id)
    
    # 基础掩膜文件（小脑和脑干）
    base_masks = [
        mask_dir / f'ref_wholecerebellum{NIFTI_EXTENSION}',
        mask_dir / f'ref_brainstem{NIFTI_EXTENSION}'
    ]
    
    # 不同处理版本的皮质下白质
    wm_variants = {
        'original': mask_dir / f'ref_subcorticalwm{NIFTI_EXTENSION}',
        'fsm8_thr07': mask_dir / f'ref_subcorticalwm_fsm8_thr07{NIFTI_EXTENSION}',
        'e1': mask_dir / f'ref_subcorticalwm_erode1{NIFTI_EXTENSION}',
        'e2': mask_dir / f'ref_subcorticalwm_erode2{NIFTI_EXTENSION}'
    }
    
    # 检查基础掩膜文件
    if not _check_required_files(base_masks):
        return False, None
    
    try:
        logger.info(f"🔄 创建多种复合参考掩膜...")
        
        # 1. 创建基于原始皮质下白质的复合参考区域
        if wm_variants['original'].exists():
            output = mask_dir / f'ref_composite{NIFTI_EXTENSION}'
            cmd = ['mri_concat'] + [str(f) for f in base_masks] + [str(wm_variants['original'])] + ['--sum', '--o', str(output)]
            utils.run_freesurfer_command(cmd, subject_id=subject_id)
            calculate_mask_stats(subject_id, output)
            logger.info(f"✅ 创建了基于原始皮质下白质的复合参考掩膜: {output}")
        else:
            logger.warning(f"⚠️ 找不到原始皮质下白质掩膜: {wm_variants['original']}")
        
        # 2. 创建基于平滑阈值化皮质下白质的复合参考区域
        if wm_variants['fsm8_thr07'].exists():
            output = mask_dir / f'ref_composite_fsm8_thr07{NIFTI_EXTENSION}'
            cmd = ['mri_concat'] + [str(f) for f in base_masks] + [str(wm_variants['fsm8_thr07'])] + ['--sum', '--o', str(output)]
            utils.run_freesurfer_command(cmd, subject_id=subject_id)
            calculate_mask_stats(subject_id, output)
            logger.info(f"✅ 创建了基于平滑阈值化皮质下白质的复合参考掩膜: {output}")
        else:
            logger.warning(f"⚠️ 找不到平滑阈值化皮质下白质掩膜: {wm_variants['fsm8_thr07']}")
        
        # 3. 创建基于不同侵蚀级别的复合参考区域
        for erode_level in [1, 2]:
            wm_key = f'e{erode_level}'
            if wm_variants[wm_key].exists():
                eroded_output = mask_dir / f'ref_composite_e{erode_level}{NIFTI_EXTENSION}'
                cmd = ['mri_concat'] + [str(f) for f in base_masks] + [str(wm_variants[wm_key])] + ['--sum', '--o', str(eroded_output)]
                utils.run_freesurfer_command(cmd, subject_id=subject_id)
                calculate_mask_stats(subject_id, eroded_output)
                logger.info(f"✅ 创建了基于侵蚀{erode_level}次皮质下白质的复合参考掩膜: {eroded_output}")
            else:
                logger.warning(f"⚠️ 找不到侵蚀{erode_level}次的白质掩膜: {wm_variants[wm_key]}")
        
        logger.info(f"✅ 所有复合参考掩膜创建完成")
        return True, mask_dir / f'ref_composite{NIFTI_EXTENSION}'
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 创建复合参考掩膜命令执行失败: {e}")
        logger.error(f"错误输出: {e.stderr if hasattr(e, 'stderr') else '未知错误'}")
        return False, None
    except Exception as e:
        logger.error(f"❌ 创建复合参考掩膜失败: {e}")
        return False, None

def create_all_masks(subject_id: str) -> Dict[str, bool]:
    """
    为指定受试者创建所有掩膜
    
    参数:
        subject_id: 受试者ID
    
    返回:
        包含各掩膜创建结果的字典
    """
    subject_id = utils.format_patient_id(subject_id)
    results = {}
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    
    # 检查FreeSurfer目录是否存在
    if not (subject_dir / 'mri').exists():
        logger.error(f"❌ 找不到FreeSurfer目录: {subject_dir}/mri")
        return {'error': False}
    
    logger.info(f"🔄 开始为受试者 {subject_id} 创建所有掩膜...")
    
    # 创建靶区掩膜（没有ref_前缀）
    target_regions = ['frontal', 'cingulate', 'parietal', 'temporal']
    for region_name in target_regions:
        success, mask_file = create_mask(subject_id, region_name, MASK_REGIONS[region_name], is_reference=False)
        results[region_name] = success
    
    # 创建复合靶区掩膜
    success, mask_file = create_composite_mask(subject_id)
    results['composite'] = success
    
    # 创建参考区域掩膜（有ref_前缀）
    reference_regions = ['cerebellumgm', 'wholecerebellum', 'brainstem', 'subcorticalwm']
    for region_name in reference_regions:
        success, mask_file = create_mask(subject_id, region_name, MASK_REGIONS[region_name], is_reference=True)
        results[f'ref_{region_name}'] = success
        
        # 为ref_subcorticalwm生成体积统计
        if region_name == 'subcorticalwm' and success and mask_file:
            calculate_mask_stats(subject_id, mask_file)
    
    # 处理皮质下白质
    wm_results = process_subcortical_wm(subject_id)
    for name, (success, _) in wm_results.items():
        results[f'subcorticalwm_{name}'] = success
    
    # 创建复合参考区域
    success, composite_file = create_composite_reference(subject_id)
    results['ref_composite'] = success
    
    # 统计成功率
    success_count = sum(1 for success in results.values() if success)
    total = len(results)
    
    logger.info(f"🎉 受试者 {subject_id} 掩膜创建完成，总计: {total}，成功: {success_count}，失败: {total - success_count}")
    return results

def process_subject_masks(subject_id: str) -> Dict[str, bool]:
    """
    处理单个受试者的所有掩膜（供并行处理使用）
    
    参数:
        subject_id: 受试者ID
    
    返回:
        包含各掩膜处理结果的字典
    """
    try:
        subject_id = utils.format_patient_id(subject_id)
        logger.info(f"🔄 开始处理受试者 {subject_id} 的掩膜...")
        results = create_all_masks(subject_id)
        return results
    except Exception as e:
        logger.error(f"❌ 处理受试者 {subject_id} 的掩膜时出错: {e}")
        return {'error': False}

def _get_optimal_workers(requested_workers: int, subject_count: int) -> int:
    """
    获取最优的并行工作进程数量
    
    参数:
        requested_workers: 请求的工作进程数
        subject_count: 受试者数量
        
    返回:
        最优的工作进程数
    """
    # 获取系统CPU核心数
    cpu_count = os.cpu_count() or 4
    
    # 不超过CPU核心数，不超过受试者数量
    optimal_workers = min(requested_workers, cpu_count, subject_count)
    
    # FreeSurfer进程很消耗资源，所以限制一下并行数
    if optimal_workers > 3 and cpu_count > 4:
        # 保留至少一个核心给操作系统
        optimal_workers = min(optimal_workers, cpu_count - 1)
    
    if optimal_workers != requested_workers:
        logger.info(f"ℹ️ 调整并行处理数量: {requested_workers} → {optimal_workers} (基于系统资源和任务数量)")
        
    return optimal_workers

def _log_mask_results(results: Dict[str, Dict[str, bool]]) -> None:
    """
    记录掩膜创建结果统计
    
    参数:
        results: 掩膜创建结果字典
    """
    if not results:
        logger.warning("⚠️ 未处理任何患者数据")
        return
        
    total_patients = len(results)
    success_patients = sum(1 for r in results.values() if 'error' not in r or r['error'] is not False)
    success_rate = (success_patients / total_patients * 100) if total_patients > 0 else 0
    
    # 计算总任务数和成功任务数
    total_tasks = sum(len(r) for r in results.values())
    success_tasks = sum(sum(1 for v in r.values() if v is True) for r in results.values())
    task_success_rate = (success_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    logger.info(f"🎉 掩膜创建完成:")
    logger.info(f"   - 受试者: {success_patients}/{total_patients} 成功 ({success_rate:.1f}%)")
    logger.info(f"   - 任务: {success_tasks}/{total_tasks} 成功 ({task_success_rate:.1f}%)")
    
    # 如果有失败，记录失败的受试者
    if success_patients < total_patients:
        failed_patients = [pid for pid, r in results.items() if 'error' in r and r['error'] is False]
        if failed_patients:
            logger.warning(f"⚠️ 以下受试者掩膜创建失败: {', '.join(failed_patients[:10])}")
            if len(failed_patients) > 10:
                logger.warning(f"   以及其他 {len(failed_patients) - 10} 个受试者")

def create_masks_for_patients(patient_ids: List[str], max_workers: int = 8) -> Dict[str, Dict[str, bool]]:
    """
    为多个受试者创建掩膜
    
    参数:
        patient_ids: 受试者ID列表
        max_workers: 最大并行处理数
    
    返回:
        包含每个受试者掩膜处理结果的字典
    """
    # 参数验证
    if not patient_ids:
        logger.warning("⚠️ 未提供任何患者ID，无法进行处理")
        return {}
    
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    # 获取最优并行数
    optimal_workers = _get_optimal_workers(max_workers, len(formatted_ids))
    
    logger.info(f"🔄 开始为 {len(formatted_ids)} 个患者创建掩膜...")
    results = {}
    
    # 并行处理
    with tqdm(total=len(formatted_ids), desc="掩膜创建进度") as pbar:
        with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_workers) as executor:
            # 提交所有任务
            future_to_patient = {
                executor.submit(process_subject_masks, pid): pid
                for pid in formatted_ids
            }
            
            # 处理完成的任务
            for future in concurrent.futures.as_completed(future_to_patient):
                pid = future_to_patient[future]
                try:
                    result = future.result()
                    results[pid] = result
                except concurrent.futures.CancelledError:
                    logger.error(f"❌ 受试者 {pid} 的任务被取消")
                    results[pid] = {'error': False}
                except Exception as e:
                    logger.error(f"❌ 处理受试者 {pid} 的掩膜时出错: {e}")
                    results[pid] = {'error': False}
                finally:
                    pbar.update(1)
    
    # 统计并记录结果
    _log_mask_results(results)
    
    return results

def create_masks_for_range(start_subj: int, end_subj: int, max_workers: int = 8) -> Dict[str, Dict[str, bool]]:
    """
    为指定范围内的受试者创建掩膜
    
    参数:
        start_subj: 起始受试者编号
        end_subj: 结束受试者编号
        max_workers: 最大并行处理数
    
    返回:
        包含每个受试者掩膜处理结果的字典
    """
    # 参数验证
    if start_subj > end_subj:
        logger.error(f"❌ 无效的受试者范围: {start_subj}-{end_subj}")
        return {}
    
    # 生成患者ID列表
    patient_ids = [str(i) for i in range(start_subj, end_subj + 1)]
    logger.info(f"开始处理患者范围 {start_subj}-{end_subj}，共 {len(patient_ids)} 个患者")
    
    # 使用通用患者处理函数
    return create_masks_for_patients(patient_ids, max_workers)
