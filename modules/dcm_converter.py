# modules/dcm_converter.py
import os
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Union, Optional, Tuple, Any, Callable
import concurrent.futures
from tqdm import tqdm
from functools import partial

from . import utils
import config

logger = logging.getLogger(__name__)

def convert_dcm_to_nifti(
    patient_id: str,
    dcm_dir: Path,
    output_dir: Optional[Path] = None,
    options: Optional[Dict] = None
) -> Tuple[bool, Optional[Path]]:
    """
    将单个患者的DICOM文件转换为NIfTI格式
    
    参数:
        patient_id: 患者ID
        dcm_dir: DICOM目录
        output_dir: 输出目录，默认与dcm_dir相同
        options: dcm2niix选项
        
    返回:
        成功标志和生成的NIfTI文件路径
    """
    patient_id = utils.format_patient_id(patient_id)
    
    # 设置默认选项
    options = options or config.DCM2NIIX_OPTIONS.copy()
        
    # 默认输出到源目录
    output_dir = output_dir or dcm_dir.parent
        
    # 确保目录存在
    if not dcm_dir.exists():
        logger.error(f"❌ DICOM目录不存在: {dcm_dir}")
        return False, None
        
    # 准备dcm2niix命令
    cmd = [config.DCM2NIIX_PATH]
    
    # 添加选项
    if 'filename' in options:
        cmd.extend(['-f', options['filename']])
        
    if 'output_dir' in options and options['output_dir']:
        cmd.extend(['-o', options['output_dir']])
    else:
        cmd.extend(['-o', str(output_dir)])
        
    if 'format' in options:
        cmd.extend(['-z', 'y' if options['format'] == '.nii.gz' else 'n'])
        
    if 'bids' in options and options['bids']:
        cmd.extend(['-b', 'y'])
        
    # 添加DICOM目录
    cmd.append(str(dcm_dir))
    
    try:
        # 执行命令
        logger.info(f"🔄 执行转换命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, text=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # 查找生成的NIfTI文件
        nifti_format = options.get('format', '.nii.gz')
        nifti_files = list(output_dir.glob(f"*{nifti_format}"))
        if not nifti_files:
            logger.error(f"❌ 转换成功但未找到输出的NIfTI文件: {output_dir}")
            return False, None
            
        # 返回第一个找到的文件
        logger.info(f"✅ 转换成功: {nifti_files[0]}")
        return True, nifti_files[0]
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 转换DICOM失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return False, None
    except Exception as e:
        logger.error(f"❌ 转换过程中出现异常: {e}")
        return False, None

def convert_patient_mr(patient_id: str) -> Tuple[bool, Optional[Path]]:
    """
    转换单个患者的MR DICOM文件
    
    参数:
        patient_id: 患者ID
        
    返回:
        成功标志和生成的NIfTI文件路径
    """
    patient_id = utils.format_patient_id(patient_id)
    
    # 确定DICOM目录
    patient_dir = config.MR_DIR / patient_id
    dcm_dir = patient_dir / f"{patient_id}_mr"
    
    if not dcm_dir.exists():
        logger.warning(f"⚠️ 患者MR DICOM目录不存在: {dcm_dir}")
        return False, None
        
    # 检查是否已存在NIfTI文件
    nifti_file = patient_dir / f"{patient_id}_mr.nii.gz"
    if nifti_file.exists():
        logger.info(f"⚠️ 患者MR NIfTI文件已存在: {nifti_file}")
        return True, nifti_file
        
    # 设置输出选项，确保输出到正确位置并使用正确的文件名
    options = config.DCM2NIIX_OPTIONS.copy()
    options['filename'] = f"{patient_id}_mr"
    
    # 执行转换
    return convert_dcm_to_nifti(patient_id, dcm_dir, patient_dir, options)

def convert_patient_pet(patient_id: str) -> Tuple[bool, List[Path]]:
    """
    转换单个患者的PET DICOM文件，包括所有重建变体
    
    参数:
        patient_id: 患者ID
        
    返回:
        成功标志和生成的NIfTI文件路径列表
    """
    patient_id = utils.format_patient_id(patient_id)
    
    # 确定患者PET目录
    patient_dir = config.PET_DIR / patient_id
    
    if not patient_dir.exists():
        logger.warning(f"⚠️ 患者PET目录不存在: {patient_dir}")
        return False, []
    
    # 查找所有PET DICOM目录（原始和变体）
    pet_dcm_dirs = list(patient_dir.glob(f"{patient_id}_pet*"))
    
    if not pet_dcm_dirs:
        logger.warning(f"⚠️ 患者PET DICOM目录不存在: {patient_dir}/...)")
        return False, []
    
    # 检查是否已存在NIfTI文件
    existing_pet_files = list(patient_dir.glob(f"{patient_id}_pet*.nii.gz"))
    if existing_pet_files:
        logger.info(f"⚠️ 患者PET NIfTI文件已存在: {', '.join(str(f) for f in existing_pet_files)}")
        return True, existing_pet_files
    
    # 转换结果
    all_success = True
    output_files = []
    
    # 处理每个PET DICOM目录
    for dcm_dir in pet_dcm_dirs:
        # 获取文件夹名称作为输出文件名
        dir_name = dcm_dir.name
        
        # 设置输出选项，确保输出到正确位置并使用正确的文件名
        options = config.DCM2NIIX_OPTIONS.copy()
        options['filename'] = dir_name
        
        logger.info(f"🔍 处理PET变体: {dir_name}")
        
        # 执行转换
        success, output_file = convert_dcm_to_nifti(
            patient_id, dcm_dir, patient_dir, options
        )
        
        all_success = all_success and success
        
        if success and output_file:
            output_files.append(output_file)
    
    # 返回所有找到的PET NIfTI文件
    if all_success and output_files:
        return True, output_files
    else:
        # 即使有部分失败，仍返回所有已转换的文件
        all_pet_files = list(patient_dir.glob(f"{patient_id}_pet*.nii.gz"))
        return all_success, all_pet_files

def convert_patient_data(patient_id: str) -> Dict[str, Union[bool, List[Path], Path]]:
    """
    转换单个患者的所有数据(MR和PET)
    
    参数:
        patient_id: 患者ID
        
    返回:
        包含转换结果的字典
    """
    patient_id = utils.format_patient_id(patient_id)
    
    # 转换MR
    mr_success, mr_file = convert_patient_mr(patient_id)
    
    # 转换PET
    pet_success, pet_files = convert_patient_pet(patient_id)
    
    result = {
        'id': patient_id,
        'mr_success': mr_success,
        'mr_file': mr_file,
        'pet_success': pet_success,
        'pet_files': pet_files
    }
    
    logger.info(f"🧾 患者 {patient_id} 转换结果: MR({mr_success}), PET({pet_success}, {len(pet_files)}个文件)")
    
    return result

def _create_error_result(patient_id: str, modality: str, error: Exception) -> Dict[str, Any]:
    """创建错误结果字典"""
    result = {'id': patient_id, 'error': str(error)}
    
    if modality == 'mr':
        result.update({'mr_success': False, 'mr_file': None})
    elif modality == 'pet':
        result.update({'pet_success': False, 'pet_files': []})
    else:  # both
        result.update({
            'mr_success': False, 'mr_file': None,
            'pet_success': False, 'pet_files': []
        })
        
    return result

def _process_with_executor(
    patient_ids: List[str],
    processor_func: Callable,
    modality: str,
    max_workers: int,
    desc: str
) -> Dict[str, Dict]:
    """使用进程池处理多个患者数据"""
    results = {}
    
    with tqdm(total=len(patient_ids), desc=desc) as pbar:
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 创建任务映射
            future_to_id = {
                executor.submit(processor_func, pid): pid
                for pid in patient_ids
            }
            
            # 处理完成的任务
            for future in concurrent.futures.as_completed(future_to_id):
                pid = future_to_id[future]
                try:
                    result = future.result()
                    results[pid] = result
                except Exception as e:
                    logger.error(f"❌ 处理患者 {pid} 数据时出错: {e}")
                    results[pid] = _create_error_result(pid, modality, e)
                finally:
                    pbar.update(1)
    
    return results

def _log_conversion_results(results: Dict[str, Dict], modality: str) -> None:
    """打印转换结果统计"""
    mr_success = sum(1 for r in results.values() if r.get('mr_success', False))
    pet_success = sum(1 for r in results.values() if r.get('pet_success', False))
    total = len(results)
    
    if modality == 'mr':
        logger.info(f"🎉 MR转换完成，总计: {total}，成功: {mr_success}, 失败: {total - mr_success}")
    elif modality == 'pet':
        logger.info(f"🎉 PET转换完成，总计: {total}，成功: {pet_success}, 失败: {total - pet_success}")
    else:
        logger.info(f"🎉 数据转换完成，总计: {total}，MR成功: {mr_success}, PET成功: {pet_success}")

def _process_batch_conversion(
    patient_ids: List[str],
    modality: str,
    max_workers: int
) -> Dict[str, Dict]:
    """批量处理患者转换通用逻辑"""
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    if modality == 'mr':
        # 仅转换MR
        processor_func = convert_patient_mr
        desc = "MR转换进度"
        
        # 特殊处理MR的结果格式
        results = {}
        raw_results = _process_with_executor(formatted_ids, processor_func, modality, max_workers, desc)
        
        for pid, (success, mr_file) in raw_results.items():
            results[pid] = {
                'id': pid,
                'mr_success': success,
                'mr_file': mr_file
            }
    
    elif modality == 'pet':
        # 仅转换PET
        processor_func = convert_patient_pet
        desc = "PET转换进度"
        
        # 特殊处理PET的结果格式
        results = {}
        raw_results = _process_with_executor(formatted_ids, processor_func, modality, max_workers, desc)
        
        for pid, (success, pet_files) in raw_results.items():
            results[pid] = {
                'id': pid,
                'pet_success': success,
                'pet_files': pet_files
            }
    
    else:
        # 转换两种模态
        processor_func = convert_patient_data
        desc = "数据转换进度"
        results = _process_with_executor(formatted_ids, processor_func, modality, max_workers, desc)
    
    # 统计结果
    _log_conversion_results(results, modality)
    
    return results

def convert_patient_range(
    start_subj: int, 
    end_subj: int, 
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    批量转换指定范围内患者的DICOM数据
    
    参数:
        start_subj: 起始患者编号
        end_subj: 结束患者编号
        modality: 转换模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者转换结果的字典
    """
    # 生成患者ID列表
    patient_ids = [str(i) for i in range(start_subj, end_subj + 1)]
    return _process_batch_conversion(patient_ids, modality, max_workers)

def convert_patient_ids(
    patient_ids: List[str],
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    批量转换指定ID列表患者的DICOM数据
    
    参数:
        patient_ids: 患者ID列表
        modality: 转换模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者转换结果的字典
    """
    return _process_batch_conversion(patient_ids, modality, max_workers)

def convert_from_range_str(
    range_str: str,
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    从范围字符串批量转换患者数据
    
    参数:
        range_str: 患者范围字符串，如"1-5,7,9-11"
        modality: 转换模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者转换结果的字典
    """
    patient_ids = utils.parse_patient_range(range_str)
    return convert_patient_ids(patient_ids, modality, max_workers)