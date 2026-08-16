# modules/utils.py
import os
import re
import logging
import subprocess
import multiprocessing
from pathlib import Path
from datetime import datetime
from typing import List, Union, Dict, Optional, Tuple, Any, Callable

# 常量定义
NIFTI_EXTENSION = ".nii.gz"
DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
SUCCESS_EMOJI = "✅"
WARNING_EMOJI = "⚠️"
ERROR_EMOJI = "❌"

# 初始化日志
logger = logging.getLogger(__name__)


# ========== 日志和环境函数 ==========

def setup_logging(log_level: str = 'INFO') -> None:
    """
    设置日志系统
    
    参数:
        log_level: 日志级别，默认为'INFO'
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"无效的日志级别: {log_level}")
        
    logging.basicConfig(
        level=numeric_level,
        format=DEFAULT_LOG_FORMAT
    )
    logger.debug(f"日志系统已设置为 {log_level} 级别")


def get_optimal_workers(max_workers: Optional[int] = None) -> int:
    """
    获取最优的并行工作线程数
    
    参数:
        max_workers: 用户指定的最大工作线程数，如果为None则自动计算
        
    返回:
        最优的工作线程数
    """
    cpu_count = multiprocessing.cpu_count()
    
    if max_workers is None:
        # 使用CPU核心数的75%作为默认值，至少1个
        return max(1, int(cpu_count * 0.75))
    else:
        # 确保不超过CPU核心数
        return min(max_workers, cpu_count)


def setup_freesurfer_env() -> Dict[str, str]:
    """
    设置FreeSurfer环境变量
    
    返回:
        设置好的环境变量字典
    """
    import config
    
    # 设置必要的环境变量
    env_vars = {
        'FREESURFER_HOME': config.FREESURFER_HOME,
        'FSFAST_HOME': config.FSFAST_HOME,
        'SUBJECTS_DIR': config.SUBJECTS_DIR,
        'MNI_DIR': config.MNI_DIR,
        'FSF_OUTPUT_FORMAT': config.FSF_OUTPUT_FORMAT,
        'FS_ALLOW_DEEP': config.FS_ALLOW_DEEP
    }
    
    # 可选的FSL配置
    if hasattr(config, 'FSL_DIR'):
        env_vars['FSL_DIR'] = config.FSL_DIR
    
    # 更新环境变量
    os.environ.update(env_vars)
    
    # 设置PATH以包含FreeSurfer bin目录
    freesurfer_bin = os.path.join(config.FREESURFER_HOME, 'bin')
    os.environ['PATH'] = f"{freesurfer_bin}:{os.environ.get('PATH', '')}"
    
    logger.info(f"{SUCCESS_EMOJI} FreeSurfer环境设置成功")
    return os.environ.copy()  # 返回设置好的环境变量副本


# ========== 患者ID和路径处理函数 ==========

def format_patient_id(patient_id: Union[int, str]) -> str:
    """
    将患者ID格式化为三位数字符串
    
    参数:
        patient_id: 患者ID（整数或字符串）
        
    返回:
        格式化的患者ID，如"001"
    """
    return f"{int(patient_id):03d}"


def parse_patient_range(range_str: str) -> List[str]:
    """
    解析患者范围字符串
    
    参数:
        range_str: 范围字符串，如"1-5", "1,3,5", "1-3,5,7-9"
        
    返回:
        格式化的ID列表，如["001", "002", ...]
    """
    if not range_str:
        return []
        
    patient_ids = []
    parts = range_str.split(',')
    
    for part in parts:
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                patient_ids.extend(range(start, end + 1))
            except ValueError:
                logger.warning(f"{WARNING_EMOJI} 无法解析范围: {part}，跳过")
        else:
            try:
                patient_ids.append(int(part))
            except ValueError:
                logger.warning(f"{WARNING_EMOJI} 无法解析ID: {part}，跳过")
    
    return [format_patient_id(pid) for pid in patient_ids]


def get_pet_variants(patient_id: str, pet_dir: Path) -> List[Path]:
    """
    检测患者的PET变体序列
    
    参数:
        patient_id: 患者ID
        pet_dir: PET数据目录
        
    返回:
        PET变体文件路径列表，如[Path("001_PET-1.nii.gz"), ...]
    """
    patient_id = format_patient_id(patient_id)
    pattern = f"{patient_id}_PET-*{NIFTI_EXTENSION}"
    variants = list(pet_dir.glob(pattern))
    
    if not variants:
        logger.debug(f"未找到患者 {patient_id} 的PET变体")
    else:
        logger.debug(f"找到患者 {patient_id} 的 {len(variants)} 个PET变体")
        
    return variants


# ========== 命令执行函数 ==========

def run_freesurfer_command(
    cmd: Union[str, List[str]], 
    env: Optional[Dict[str, str]] = None, 
    save_output: bool = True, 
    subject_id: Optional[str] = None
) -> subprocess.CompletedProcess:
    """
    使用正确的环境执行FreeSurfer命令
    
    参数:
        cmd: 要执行的命令(字符串或列表)
        env: 可选的环境变量字典，如果为None则使用setup_freesurfer_env()设置
        save_output: 是否保存命令输出到日志文件
        subject_id: 处理的受试者ID，用于按受试者组织日志文件
        
    返回:
        subprocess.CompletedProcess对象
    """
    if env is None:
        env = setup_freesurfer_env()
        
    # 确保命令是列表形式
    command = cmd if isinstance(cmd, list) else cmd.split()
    
    cmd_name = os.path.basename(command[0])
    cmd_str = ' '.join(command)
    logger.info(f"执行FreeSurfer命令: {cmd_str}")
    
    try:
        result = subprocess.run(
            command,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 记录简短的输出摘要到日志
        _log_command_output_summary(result)
        
        # 保存详细输出到日志文件
        if save_output:
            _save_command_output_to_file(result, cmd_str, cmd_name, subject_id)
        
        return result
    
    except subprocess.CalledProcessError as e:
        logger.error(f"{ERROR_EMOJI} FreeSurfer命令执行失败: {e}")
        # 记录错误输出
        if e.stdout:
            logger.debug(f"命令标准输出: {e.stdout[:500]}...")
        if e.stderr:
            logger.debug(f"命令错误输出: {e.stderr[:500]}...")
        raise


def _log_command_output_summary(result: subprocess.CompletedProcess) -> None:
    """记录命令输出摘要到日志"""
    stdout_lines = result.stdout.splitlines()
    stderr_lines = result.stderr.splitlines()
    
    if stdout_lines:
        logger.debug(f"命令输出 ({len(stdout_lines)}行): {stdout_lines[0]}...")
    if stderr_lines:
        logger.debug(f"命令错误 ({len(stderr_lines)}行): {stderr_lines[0]}...")


def _save_command_output_to_file(
    result: subprocess.CompletedProcess, 
    cmd_str: str, 
    cmd_name: str, 
    subject_id: Optional[str] = None
) -> None:
    """保存命令输出到日志文件"""
    import config
    
    # 确保日志目录结构存在
    log_dir = Path(config.LOG_DIR)
    
    # 确定日志目录路径
    if subject_id:
        # 格式化ID（如果需要）
        formatted_id = format_patient_id(subject_id) if not isinstance(subject_id, str) or len(subject_id) != 3 else subject_id
        # 按受试者ID和命令类型组织日志
        log_dir = log_dir / formatted_id / cmd_name
    else:
        # 通用日志目录
        log_dir = log_dir / "freesurfer_outputs" / cmd_name
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成唯一的日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{timestamp}.log"
    
    with open(log_file, 'w') as f:
        f.write(f"命令: {cmd_str}\n")
        f.write(f"时间: {get_datetime()}\n")
        f.write(f"状态: {'成功' if result.returncode == 0 else '失败'}\n")
        f.write("\n--- 标准输出 ---\n")
        f.write(result.stdout)
        f.write("\n--- 错误输出 ---\n")
        f.write(result.stderr)
    
    logger.info(f"{SUCCESS_EMOJI} FreeSurfer命令输出已保存到: {log_file}")


# ========== 时间和日期函数 ==========

def get_datetime() -> str:
    """
    获取当前日期和时间的格式化字符串
    
    返回:
        格式化的日期时间字符串，格式为: YYYY-MM-DD HH:MM:SS
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")