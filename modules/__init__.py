# modules/__init__.py

"""
AMYPET处理系统 - 功能模块包

包含以下功能模块：
- utils: 通用工具函数
- directory_renamer: 目录重命名
- dcm_converter: DICOM转换
- header_extractor: Header提取
- recon_processor: FreeSurfer重建
- recon_status: FreeSurfer状态检查
- registration: 图像配准
- mask_processor: 掩膜制作
- suvr_calculator: SUVR计算
- pet_pvc_processor: PET部分容积校正
- pvc_suvr_calculator: PVC校正SUVR计算
- delete: 文件删除
- check: 结果检查
"""

# 核心工具
from . import utils

# 数据处理模块
from . import directory_renamer
from . import dcm_converter
from . import header_extractor

# 图像处理模块
from . import recon_processor
from . import recon_status
from . import registration
from . import mask_processor
from . import suvr_calculator
from . import pet_pvc_processor
from . import pvc_suvr_calculator
from . import check


__version__ = '1.0.0'
__author__ = 'hayabusasxs'