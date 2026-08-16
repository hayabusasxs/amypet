# config.py
import os
import re
import sys
from pathlib import Path
import subprocess

# 项目主目录 (基于当前文件所在路径动态获取)
PROJECT_ROOT = Path(__file__).resolve().parent

# 获取FreeSurfer版本
def detect_fs_version() -> str:
    """自动检测系统中的 FreeSurfer 版本号"""
    # 1. 优先从环境变量 FREESURFER_HOME 中检测
    fs_home = os.environ.get('FREESURFER_HOME')
    if fs_home:
        # 尝试读取 build-stamp.txt
        build_stamp = Path(fs_home) / 'build-stamp.txt'
        if build_stamp.exists():
            try:
                content = build_stamp.read_text().strip()
                # 匹配类似 7.4.1 或 8.0.0
                match = re.search(r'(\d+\.\d+\.?\d*)', content)
                if match:
                    return match.group(1)
            except Exception:
                pass
        # 尝试从路径名匹配版本号
        match = re.search(r'freesurfer[_-]?v?(\d+\.\d+\.?\d*)', fs_home, re.IGNORECASE)
        if match:
            return match.group(1)

    # 2. 从用户配置文件中尝试查找 (~/.zshrc, ~/.bashrc, ~/.bash_profile)
    home_dir = Path.home()
    for profile_name in ['.zshrc', '.bashrc', '.bash_profile', '.profile']:
        profile_path = home_dir / profile_name
        if profile_path.exists():
            try:
                with open(profile_path, 'r', encoding='utf-8', errors='ignore') as file:
                    for line in file:
                        if 'FREESURFER_HOME=' in line and not line.strip().startswith('#'):
                            match = re.search(r'/freesurfer_([^/\s"\']+)', line)
                            if match:
                                return match.group(1)
                            match = re.search(r'(\d+\.\d+\.?\d*)', line)
                            if match:
                                return match.group(1)
            except Exception:
                pass

    # 3. 默认回退版本
    return '8.0.0'

# FreeSurfer版本配置
FS_VERSION = detect_fs_version()

# 基础数据路径 (可通过环境变量 AMYPET_DATA_ROOT 覆盖，默认在项目根目录下)
ROOT_DIR = Path(os.environ.get('AMYPET_DATA_ROOT', PROJECT_ROOT))
DATA_DIR = ROOT_DIR / 'data'
MR_DIR = DATA_DIR / 'mr'
PET_DIR = DATA_DIR / 'pet'

# 版本相关路径
# 重建目录，根据版本设置不同目录
RECON_BASE = 'recon'  # 基础名称
RECON_SUFFIX = f"_{FS_VERSION}" if FS_VERSION else ''  # 版本后缀
RECON_DIR = DATA_DIR / f"{RECON_BASE}{RECON_SUFFIX}"

# 数据表格目录
SHEET_DIR_BASE = 'sheet'  # 基础名称
SHEET_DIR_SUFFIX = f"_{FS_VERSION}" if FS_VERSION else ''  # 版本后缀
SHEET_DIR = DATA_DIR / f"{SHEET_DIR_BASE}{SHEET_DIR_SUFFIX}"

# 患者信息表格路径
PATIENT_DATA_INFO = SHEET_DIR / 'patient_data_info.xlsx'

# FreeSurfer环境设置
# 优先读取环境变量，否则使用用户主目录或默认安装路径
_default_fs_base = os.environ.get('FREESURFER_HOME')
if not _default_fs_base:
    _home_fs = Path.home() / f"freesurfer_{FS_VERSION}"
    if _home_fs.exists():
        _default_fs_base = str(_home_fs)
    else:
        _default_fs_base = f"/usr/local/freesurfer_{FS_VERSION}"

FREESURFER_HOME = str(os.environ.get('FREESURFER_HOME', _default_fs_base))
FS_BASE_PATH = FREESURFER_HOME
FS_PATH_SUFFIX = f"_{FS_VERSION}" if FS_VERSION != 'default' else ''
FSFAST_HOME = f"{FREESURFER_HOME}/fsfast"
SUBJECTS_DIR = str(RECON_DIR)
MNI_DIR = f"{FREESURFER_HOME}/mni"

# FSL环境设置
FSL_DIR = os.environ.get('FSLDIR', os.environ.get('FSL_DIR', str(Path.home() / 'fsl')))
FSF_OUTPUT_FORMAT = 'nii.gz'

# 其他设置
FS_ALLOW_DEEP = '1'

# DCM2NIIX配置
DCM2NIIX_PATH = os.environ.get('DCM2NIIX_PATH', 'dcm2niix')
DCM2NIIX_OPTIONS = {
    'filename': '%f',
    'output_dir': '',  # 空字符串表示与DICOM相同文件夹
    'format': '.nii.gz',
    'bids': True
}

# 日志设置
LOG_LEVEL = 'INFO'
LOG_DIR = ROOT_DIR / 'logs'

# ===== 自适应并行相关设置 =====
PERF_DETECT_STRICT_FAIL: bool = False
PERF_DETECT_TIMEOUT_SEC: float = 2.0

# FreeSurfer 8.0.x 特殊处理配置
IS_FS_8 = FS_VERSION.startswith('8.0')

# 探测物理核心数（用于默认OpenMP线程数）
def _detect_physical_cores(timeout_sec: float = 2.0) -> int:
    try:
        if sys.platform.startswith('darwin'):
            try:
                out = subprocess.run(['sysctl', '-n', 'hw.perflevel0.physicalcpu'], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
                v = int((out.stdout or '').strip())
                if v > 0: return v
            except Exception:
                pass
            try:
                out2 = subprocess.run(['sysctl', '-n', 'hw.physicalcpu'], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
                v2 = int((out2.stdout or '').strip())
                if v2 > 0: return v2
            except Exception:
                pass
        v3 = os.cpu_count() or 0
        return max(1, v3)
    except Exception:
        return 1

# 全局默认OpenMP线程数
try:
    FS8_OPENMP_THREADS = max(1, _detect_physical_cores(PERF_DETECT_TIMEOUT_SEC))
except Exception:
    FS8_OPENMP_THREADS = 8

USE_PROCESS_POOL = not IS_FS_8

# 默认并发与模态设置
DEFAULT_MAX_WORKERS = 1 if IS_FS_8 else 8
DEFAULT_MODALITY = 'both'

# 结果设置
DEFAULT_SUVR_OUTPUT_FILE = SHEET_DIR / 'all_subjects_suvr.csv'
