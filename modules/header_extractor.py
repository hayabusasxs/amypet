# modules/header_extractor.py
import os
import logging
import subprocess
import warnings
from pathlib import Path
from typing import List, Dict, Union, Optional, Tuple, Any, Callable
import concurrent.futures
from tqdm import tqdm
import pydicom  # 使用pydicom读取DICOM文件
from functools import partial

from . import utils
import config

# 过滤pydicom的VR警告
warnings.filterwarnings("ignore", message="Invalid value for VR IS")
warnings.filterwarnings("ignore", category=UserWarning, module="pydicom")

logger = logging.getLogger(__name__)

def extract_dcm_header(dcm_dir: Path, output_file: Path) -> bool:
    """
    使用pydicom提取DICOM文件头信息并保存到文件
    
    参数:
        dcm_dir: DICOM目录
        output_file: 输出文件路径
        
    返回:
        成功标志
    """
    try:
        # 查找第一个DICOM文件
        dcm_files = list(dcm_dir.glob('*.dcm'))
        if not dcm_files and dcm_dir.is_dir():  # 有些DICOM没有.dcm后缀
            dcm_files = list(dcm_dir.iterdir())
            
        if not dcm_files:
            logger.error(f"❌ 未找到DICOM文件: {dcm_dir}")
            return False
            
        # 读取DICOM文件的头信息
        dicom_data = pydicom.dcmread(str(dcm_files[0]))
        
        # 将头信息保存为纯文本文件
        with open(output_file, 'w') as f:
            f.write(str(dicom_data))  # 将DICOM数据转换为文本并写入文件
            
        logger.info(f"✅ 已保存DICOM header: {output_file}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 提取DICOM header时出现异常: {e}")
        return False

def extract_nifti_header(nifti_file: Path, output_file: Path) -> bool:
    """
    使用fslhd提取NIfTI文件头信息并保存到文件
    
    参数:
        nifti_file: NIfTI文件路径
        output_file: 输出文件路径
        
    返回:
        成功标志
    """
    try:
        # 使用FSL的fslhd提取header
        cmd = ['fslhd', str(nifti_file)]
        
        logger.info(f"🔍 提取NIfTI header: {' '.join(cmd)}")
        # 使用FreeSurfer/FSL环境执行命令
        result = subprocess.run(cmd, check=True, text=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                               env=utils.setup_freesurfer_env())
        
        # 保存header到文件
        with open(output_file, 'w') as f:
            f.write(result.stdout)
            
        logger.info(f"✅ 已保存NIfTI header: {output_file}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 提取NIfTI header失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"❌ 提取NIfTI header时出现异常: {e}")
        return False

def extract_mr_headers(patient_id: str) -> Dict[str, bool]:
    """
    提取单个患者的MR相关头信息
    
    参数:
        patient_id: 患者ID
        
    返回:
        处理结果字典
    """
    patient_id = utils.format_patient_id(patient_id)
    result = {
        'id': patient_id,
        'dcm_header_success': False,
        'nifti_header_success': False,
        'json_exists': False
    }
    
    # 定义路径
    patient_dir = config.MR_DIR / patient_id
    dcm_dir = patient_dir / f"{patient_id}_mr"
    nifti_file = patient_dir / f"{patient_id}_mr.nii.gz"
    dcm_header_file = patient_dir / f"{patient_id}_mr.dcm.header"
    nifti_header_file = patient_dir / f"{patient_id}_mr.nii.gz.header"
    json_file = patient_dir / f"{patient_id}_mr.json"
    
    # 检查目录和文件是否存在
    if not patient_dir.exists():
        logger.warning(f"⚠️ 患者MR目录不存在: {patient_dir}")
        return result
        
    # 提取DICOM header
    if dcm_dir.exists():
        result['dcm_header_success'] = extract_dcm_header(dcm_dir, dcm_header_file)
    else:
        logger.warning(f"⚠️ 患者MR DICOM目录不存在: {dcm_dir}")
    
    # 提取NIfTI header
    if nifti_file.exists():
        result['nifti_header_success'] = extract_nifti_header(nifti_file, nifti_header_file)
    else:
        logger.warning(f"⚠️ 患者MR NIfTI文件不存在: {nifti_file}")
    
    # 检查JSON文件是否存在
    result['json_exists'] = json_file.exists()
    
    logger.info(f"📋 患者 {patient_id} MR header提取结果: DICOM({result['dcm_header_success']}), "
                f"NIfTI({result['nifti_header_success']}), JSON({result['json_exists']})")
    return result

def extract_pet_headers(patient_id: str) -> Dict[str, Any]:
    """
    提取单个患者的PET相关头信息，包括原始和重建版本
    
    参数:
        patient_id: 患者ID
        
    返回:
        处理结果字典
    """
    patient_id = utils.format_patient_id(patient_id)
    result = {
        'id': patient_id,
        'dcm_header_success': {},  # 使用字典记录各个版本的成功状态
        'nifti_header_success': {},  # 记录各个变体的NIfTI header提取状态
        'json_exists': False,
        'pet_variants': []
    }
    
    # 定义路径
    patient_dir = config.PET_DIR / patient_id
    
    # 检查目录是否存在
    if not patient_dir.exists():
        logger.warning(f"⚠️ 患者PET目录不存在: {patient_dir}")
        return result
    
    # 首先查找所有可能的PET DICOM目录（原始和变体）
    all_pet_dirs = []
    
    # 检查原始PET目录
    original_dcm_dir = patient_dir / f"{patient_id}_pet"
    if original_dcm_dir.exists() and original_dcm_dir.is_dir():
        all_pet_dirs.append(('original', original_dcm_dir))
        
    # 查找PET重建变体目录
    pet_variant_dirs = [p for p in patient_dir.glob(f"{patient_id}_pet-*") if p.is_dir()]
    for variant_dir in pet_variant_dirs:
        variant_name = variant_dir.name
        all_pet_dirs.append((variant_name, variant_dir))
        result['pet_variants'].append(variant_name)
    
    # 如果既没有原始目录也没有变体目录，记录调试信息而不是警告
    if not all_pet_dirs:
        logger.debug(f"🔍 患者 {patient_id} 没有找到PET DICOM目录，将只处理NIfTI文件")
    else:
        # 处理找到的所有PET DICOM目录
        for dir_type, dcm_dir in all_pet_dirs:
            if dir_type == 'original':
                dcm_header_file = patient_dir / f"{patient_id}_pet.dcm.header"
            else:
                dcm_header_file = patient_dir / f"{dir_type}.dcm.header"
                
            dcm_success = extract_dcm_header(dcm_dir, dcm_header_file)
            result['dcm_header_success'][dir_type] = dcm_success
            
            status_emoji = '✅' if dcm_success else '❌'
            if dir_type == 'original':
                logger.info(f"📊 原始PET DICOM header提取: {status_emoji}")
            else:
                logger.info(f"📊 PET变体 {dir_type} DICOM header提取: {status_emoji}")
    
    # 提取所有PET NIfTI文件的header
    pet_nifti_files = list(patient_dir.glob(f"{patient_id}_pet*.nii.gz"))
    if not pet_nifti_files:
        logger.debug(f"🔍 患者 {patient_id} 未找到PET NIfTI文件: {patient_dir}")
        # 如果既没有DICOM也没有NIfTI文件，才返回空结果
        if not all_pet_dirs:
            return result
    else:
        # 处理原始PET NIfTI和变体
        for nifti_file in pet_nifti_files:
            nifti_name = nifti_file.name.replace('.nii.gz', '')
            nifti_header_file = patient_dir / f"{nifti_name}.nii.gz.header"
            nifti_header_success = extract_nifti_header(nifti_file, nifti_header_file)
            result['nifti_header_success'][nifti_name] = nifti_header_success
            logger.info(f"📊 PET NIfTI {nifti_name} header提取: {'✅' if nifti_header_success else '❌'}")
    
    # 检查JSON文件是否存在
    json_file = patient_dir / f"{patient_id}_pet.json"
    result['json_exists'] = json_file.exists()
    
    # 总结结果
    dcm_success_count = sum(1 for s in result['dcm_header_success'].values() if s)
    total_dcm_variants = len(result['dcm_header_success'])
    
    nifti_success_count = sum(1 for s in result['nifti_header_success'].values() if s)
    total_nifti_variants = len(result['nifti_header_success'])
    
    logger.info(f"📋 患者 {patient_id} PET header提取结果: "
                f"DICOM({dcm_success_count}/{total_dcm_variants}成功), "
                f"NIfTI({nifti_success_count}/{total_nifti_variants}成功), "
                f"JSON({result['json_exists']}), "
                f"变体: {', '.join(result['pet_variants']) if result['pet_variants'] else '无'}")
    return result

def extract_patient_headers(patient_id: str, modality: str = 'both') -> Dict[str, Dict]:
    """
    提取单个患者的所有相关头信息
    
    参数:
        patient_id: 患者ID
        modality: 处理模态，可选'mr', 'pet', 'both'
        
    返回:
        处理结果字典
    """
    patient_id = utils.format_patient_id(patient_id)
    result = {'id': patient_id}
    
    if modality in ['mr', 'both']:
        mr_result = extract_mr_headers(patient_id)
        result['mr'] = mr_result
        
    if modality in ['pet', 'both']:
        pet_result = extract_pet_headers(patient_id)
        result['pet'] = pet_result
        
    logger.info(f"🧾 患者 {patient_id} header提取完成")
    return result

def _create_error_result(patient_id: str) -> Dict[str, Any]:
    """创建错误结果字典"""
    return {
        'id': patient_id,
        'error': True
    }

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
                executor.submit(processor_func, pid, modality): pid
                for pid in patient_ids
            }
            
            # 处理完成的任务
            for future in concurrent.futures.as_completed(future_to_id):
                pid = future_to_id[future]
                try:
                    result = future.result()
                    results[pid] = result
                except Exception as e:
                    logger.error(f"❌ 提取患者 {pid} header时出错: {e}")
                    results[pid] = {
                        'id': pid,
                        'error': str(e)
                    }
                finally:
                    pbar.update(1)
    
    return results

def _calculate_extraction_success(results: Dict[str, Dict], modality: str) -> Tuple[int, int]:
    """计算提取成功的数量"""
    mr_success = 0
    pet_success = 0
    
    if modality in ['mr', 'both']:
        mr_success = sum(1 for r in results.values() 
                      if 'mr' in r and r['mr'].get('dcm_header_success', False) and r['mr'].get('nifti_header_success', False))
    
    if modality in ['pet', 'both']:
        for r in results.values():
            if 'pet' in r and isinstance(r['pet'], dict):
                dcm_success_any = any(s for s in r['pet'].get('dcm_header_success', {}).values() if isinstance(s, bool) and s)
                
                nifti_success_any = any(s for s in r['pet'].get('nifti_header_success', {}).values() if isinstance(s, bool) and s)
                
                # 只要有DICOM或NIfTI header提取成功就算成功（适应没有原始DICOM的情况）
                if dcm_success_any or nifti_success_any:
                    pet_success += 1
    
    return mr_success, pet_success

def _log_extraction_results(results: Dict[str, Dict], modality: str) -> None:
    """打印提取结果统计"""
    mr_success, pet_success = _calculate_extraction_success(results, modality)
    total = len(results)
    
    if modality == 'mr':
        logger.info(f"🎉 MR header提取完成，总计: {total}，成功: {mr_success}, 失败: {total - mr_success}")
    elif modality == 'pet':
        logger.info(f"🎉 PET header提取完成，总计: {total}，成功: {pet_success}, 失败: {total - pet_success}")
    else:
        logger.info(f"🎉 header提取完成，总计: {total}，MR成功: {mr_success}, PET成功: {pet_success}")

def _process_batch_extraction(
    patient_ids: List[str],
    modality: str,
    max_workers: int
) -> Dict[str, Dict]:
    """批量处理患者头信息提取通用逻辑"""
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    
    # 使用进程池并行处理
    results = _process_with_executor(
        formatted_ids, 
        extract_patient_headers, 
        modality, 
        max_workers, 
        "header提取进度"
    )
    
    # 统计结果
    _log_extraction_results(results, modality)
    
    return results

def extract_headers_from_range(
    start_subj: int, 
    end_subj: int, 
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    批量提取指定范围内患者的头信息
    
    参数:
        start_subj: 起始患者编号
        end_subj: 结束患者编号
        modality: 处理模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者处理结果的字典
    """
    # 生成患者ID列表
    patient_ids = [str(i) for i in range(start_subj, end_subj + 1)]
    return _process_batch_extraction(patient_ids, modality, max_workers)

def extract_headers_from_patient_ids(
    patient_ids: List[str],
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    批量提取指定ID列表患者的头信息
    
    参数:
        patient_ids: 患者ID列表
        modality: 处理模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者处理结果的字典
    """
    return _process_batch_extraction(patient_ids, modality, max_workers)

def extract_headers_from_range_str(
    range_str: str,
    modality: str = 'both',
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    从范围字符串批量提取患者头信息
    
    参数:
        range_str: 患者范围字符串，如"1-5,7,9-11"
        modality: 处理模态，可选'mr', 'pet', 'both'
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者处理结果的字典
    """
    patient_ids = utils.parse_patient_range(range_str)
    return extract_headers_from_patient_ids(patient_ids, modality, max_workers)

def _collect_header_files(patient_id: str, modality: str) -> List[Path]:
    """收集指定患者的header文件"""
    header_files = []
    
    if modality in ['mr', 'both']:
        mr_dir = config.MR_DIR / patient_id
        if mr_dir.exists():
            header_files.extend(mr_dir.glob("*.header"))
    
    if modality in ['pet', 'both']:
        pet_dir = config.PET_DIR / patient_id
        if pet_dir.exists():
            header_files.extend(pet_dir.glob("*.header"))
            
    return header_files

def delete_patient_headers(patient_id: str, modality: str = 'both') -> Dict[str, bool]:
    """
    删除单个患者的header文件
    
    参数:
        patient_id: 患者ID
        modality: 处理模态，可选'mr', 'pet', 'both'
        
    返回:
        删除结果字典
    """
    patient_id = utils.format_patient_id(patient_id)
    result = {
        'id': patient_id,
        'mr_deleted': False,
        'pet_deleted': False
    }
    
    # 删除MR header
    if modality in ['mr', 'both']:
        mr_dir = config.MR_DIR / patient_id
        if mr_dir.exists():
            # 查找并删除所有header文件
            header_files = list(mr_dir.glob("*.header"))
            for header_file in header_files:
                try:
                    header_file.unlink()
                    logger.info(f"🗑️ 已删除MR header: {header_file}")
                except Exception as e:
                    logger.error(f"❌ 删除文件失败: {header_file}, 错误: {e}")
            
            result['mr_deleted'] = bool(header_files)
        else:
            logger.warning(f"⚠️ 患者MR目录不存在: {mr_dir}")
    
    # 删除PET header
    if modality in ['pet', 'both']:
        pet_dir = config.PET_DIR / patient_id
        if pet_dir.exists():
            # 查找并删除所有header文件
            header_files = list(pet_dir.glob("*.header"))
            for header_file in header_files:
                try:
                    header_file.unlink()
                    logger.info(f"🗑️ 已删除PET header: {header_file}")
                except Exception as e:
                    logger.error(f"❌ 删除文件失败: {header_file}, 错误: {e}")
            
            result['pet_deleted'] = bool(header_files)
        else:
            logger.warning(f"⚠️ 患者PET目录不存在: {pet_dir}")
    
    logger.info(f"🧹 患者 {patient_id} header删除完成: MR({result['mr_deleted']}), PET({result['pet_deleted']})")
    return result

def _collect_all_header_files(patient_ids: List[str], modality: str) -> List[Path]:
    """收集多个患者的所有header文件"""
    all_header_files = []
    
    for pid in patient_ids:
        patient_header_files = _collect_header_files(pid, modality)
        all_header_files.extend(patient_header_files)
        
    return all_header_files

def delete_headers_from_range(
    start_subj: int, 
    end_subj: int, 
    modality: str = 'both',
    confirm: bool = True
) -> Dict[str, Dict]:
    """
    批量删除指定范围内患者的header文件
    
    参数:
        start_subj: 起始患者编号
        end_subj: 结束患者编号
        modality: 处理模态，可选'mr', 'pet', 'both'
        confirm: 是否在删除前确认
        
    返回:
        包含每个患者删除结果的字典
    """
    # 生成患者ID列表
    patient_ids = [utils.format_patient_id(i) for i in range(start_subj, end_subj + 1)]
    
    # 先收集所有要删除的文件
    header_files = _collect_all_header_files(patient_ids, modality)
    
    # 如果没有找到文件
    if not header_files:
        logger.info("❓ 未找到任何header文件")
        return {}
    
    # 列出所有要删除的文件
    logger.info(f"🔍 找到 {len(header_files)} 个header文件:")
    for file in header_files[:10]:  # 只显示前10个
        logger.info(f"  - {file}")
    if len(header_files) > 10:
        logger.info(f"  ... 还有 {len(header_files) - 10} 个文件")
    
    # 确认删除
    if confirm and header_files:
        response = input("确认删除这些文件吗? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            logger.info("❌ 取消删除操作")
            return {}
    
    # 执行删除
    results = {}
    for pid in tqdm(patient_ids, desc="header删除进度"):
        try:
            result = delete_patient_headers(pid, modality)
            results[pid] = result
        except Exception as e:
            logger.error(f"❌ 删除患者 {pid} header时出错: {e}")
            results[pid] = {
                'id': pid,
                'error': str(e)
            }
    
    # 统计结果
    mr_deleted = sum(1 for r in results.values() if r.get('mr_deleted', False))
    pet_deleted = sum(1 for r in results.values() if r.get('pet_deleted', False))
    total = len(results)
    
    if modality == 'mr':
        logger.info(f"🎉 MR header删除完成，总计: {total}，成功: {mr_deleted}, 失败: {total - mr_deleted}")
    elif modality == 'pet':
        logger.info(f"🎉 PET header删除完成，总计: {total}，成功: {pet_deleted}, 失败: {total - pet_deleted}")
    else:
        logger.info(f"🎉 header删除完成，总计: {total}，MR成功: {mr_deleted}, PET成功: {pet_deleted}")
    
    return results

def delete_headers_from_range_str(
    range_str: str, 
    modality: str = 'both',
    confirm: bool = True
) -> Dict[str, Dict]:
    """
    从范围字符串批量删除患者头信息
    
    参数:
        range_str: 患者范围字符串，如"1-5,7,9-11"
        modality: 处理模态，可选'mr', 'pet', 'both'
        confirm: 是否在删除前确认
        
    返回:
        包含每个患者处理结果的字典
    """
    patient_ids = utils.parse_patient_range(range_str)
    
    # 收集所有要删除的文件
    header_files = _collect_all_header_files(patient_ids, modality)
    
    # 如果没有找到文件
    if not header_files:
        logger.info("❓ 未找到任何header文件")
        return {}
    
    # 列出所有要删除的文件
    logger.info(f"🔍 找到 {len(header_files)} 个header文件:")
    for file in header_files[:10]:  # 只显示前10个
        logger.info(f"  - {file}")
    if len(header_files) > 10:
        logger.info(f"  ... 还有 {len(header_files) - 10} 个文件")
    
    # 确认删除
    if confirm and header_files:
        response = input("确认删除这些文件吗? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            logger.info("❌ 取消删除操作")
            return {}
    
    # 执行删除
    results = {}
    for pid in tqdm(patient_ids, desc="header删除进度"):
        try:
            result = delete_patient_headers(pid, modality)
            results[pid] = result
        except Exception as e:
            logger.error(f"❌ 删除患者 {pid} header时出错: {e}")
            results[pid] = {
                'id': pid,
                'error': str(e)
            }
    
    # 统计结果
    mr_deleted = sum(1 for r in results.values() if r.get('mr_deleted', False))
    pet_deleted = sum(1 for r in results.values() if r.get('pet_deleted', False))
    total = len(results)
    
    if modality == 'mr':
        logger.info(f"🎉 MR header删除完成，总计: {total}，成功: {mr_deleted}, 失败: {total - mr_deleted}")
    elif modality == 'pet':
        logger.info(f"🎉 PET header删除完成，总计: {total}，成功: {pet_deleted}, 失败: {total - pet_deleted}")
    else:
        logger.info(f"🎉 header删除完成，总计: {total}，MR成功: {mr_deleted}, PET成功: {pet_deleted}")
    
    return results