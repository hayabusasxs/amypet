# modules/info_get.py
import os
import logging
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import re
from datetime import datetime


from . import utils
import config

logger = logging.getLogger(__name__)

# 在模块内部定义PATIENT_DATA_INFO，使用config中的版本化路径
PATIENT_DATA_INFO = config.PATIENT_DATA_INFO
# 新增：CSV 输出路径（与原xlsx同名改后缀）
PATIENT_DATA_INFO_CSV = PATIENT_DATA_INFO.with_suffix('.csv')

# 固定表头列顺序，确保不减少字段且顺序一致
TABLE_COLUMNS: List[str] = [
    'id', 'variant', 'manufacturer', 'patient_id', 'name', 'gender', 'age', 'weight', 'size',
    'duration', 'dose', 'radiopharm_date', 'acq_date', 'radiopharm_time', 'acq_time', 'delta_time',
    'thickness', 'rows', 'columns', 'pixel', 'dfov', 'diagnosis', 'mr_series', 'pet_series', 'modality'
]

# 为了在Excel中打开CSV时避免自动转日期/数字，以下列将以 ="值" 的形式写出
EXCEL_TEXT_COLUMNS: List[str] = [
    'id', 'variant', 'patient_id', 'mr_series', 'pet_series',
    'radiopharm_date', 'acq_date', 'radiopharm_time', 'acq_time', 'delta_time'
]


def wrap_excel_text(value: Any) -> str:
    """将值包装为Excel文本公式 ="..."，以避免Excel自动类型转换。
    空值返回空字符串；内部双引号会被加倍以保持CSV有效性。
    """
    if value is None:
        return ''
    text = str(value)
    if text == '':
        return ''
    # 如果已经是 ="..." 格式，直接返回
    if text.startswith('="') and text.endswith('"'):
        return text
    # 转义内部双引号
    text_escaped = text.replace('"', '""')
    return f'="{text_escaped}"'


def unwrap_excel_text(value: Any) -> str:
    """去除 ="..." 包装，返回内部文本。其他值原样转为字符串。"""
    if value is None:
        return ''
    text = str(value)
    if text.startswith('="') and text.endswith('"') and len(text) >= 3:
        inner = text[2:-1]
        return inner.replace('""', '"')
    return text

def extract_numeric_value(value: str) -> float:
    """从字符串中提取数值"""
    try:
        # 移除所有非数字字符（保留小数点）
        numeric_str = re.sub(r'[^\d.]', '', value)
        return float(numeric_str)
    except (ValueError, TypeError):
        return 0.0

def extract_dfov_value(value: str) -> float:
    """从DICOM值中提取DFOV数值
    
    支持两种格式：
    1. 单个数值字符串 (例如: '350.0')
    2. 数组格式 (例如: '[250.0, 250.0]')
    """
    try:
        # 去除引号和空格
        value = value.strip().strip("'\"")
        
        # 如果是数组格式 [x, y]，取第一个值
        if value.startswith('[') and value.endswith(']'):
            # 提取数组中的第一个数值
            array_content = value.strip('[]')
            values = array_content.split(',')
            if values:
                first_value = values[0].strip()
                return float(first_value)
        else:
            # 单个数值字符串，直接提取数值
            return extract_numeric_value(value)
            
    except (ValueError, TypeError, IndexError) as e:
        logger.warning(f"⚠️ 提取DFOV值失败: {value}, 错误: {e}")
        return 0.0

def parse_datetime(dt_str: str) -> Tuple[str, str]:
    """解析日期时间字符串，返回日期和时间部分"""
    try:
        # 移除所有非数字字符
        dt_str = re.sub(r'[^\d.]', '', dt_str)
        
        # 处理不同格式的时间字符串
        if '.' in dt_str:  # SIGNA PET/MR格式，包含毫秒
            dt_str = dt_str.split('.')[0]  # 移除毫秒部分
            
        # 确保字符串至少包含14位数字（年月日时分秒）
        if len(dt_str) < 14:
            return '', ''
            
        # 提取日期和时间部分
        date_part = dt_str[:8]
        time_part = dt_str[8:14]  # 只取时分秒部分
        
        return date_part, time_part
    except Exception as e:
        logger.error(f"❌ 解析日期时间失败: {dt_str}, 错误: {e}")
        return '', ''

def extract_variant(filename: str) -> str:
    """从文件名中提取变体标识"""
    try:
        # 尝试匹配 -数字.dcm.header 格式
        match = re.search(r'-([^\.]+)\.dcm\.header$', filename)
        if match:
            return match.group(1)
            
        # 尝试提取文件名中的最后一个破折号后面、.dcm.header前面的内容
        match = re.search(r'_(?:pet|mr)(?:-([^\.]+))?\.dcm\.header$', filename)
        if match and match.group(1):
            return match.group(1)
            
        # 尝试直接从文件名中获取
        basename = os.path.basename(filename)
        if '_pet-' in basename or '_mr-' in basename:
            parts = basename.split('-')
            if len(parts) > 1:
                variant_part = parts[1].split('.')[0]
                return variant_part
                
        # 如果没有找到变体信息，返回默认值
        return "00"
    except Exception as e:
        logger.warning(f"⚠️ 提取变体标识失败: {filename}, 错误: {e}")
        return "00"

def time_to_seconds(time_str: str) -> int:
    """将时间字符串转换为秒数"""
    hours = int(time_str[:2])
    minutes = int(time_str[2:4])
    seconds = int(time_str[4:])
    return hours * 3600 + minutes * 60 + seconds

def calculate_time_difference(radiopharm_date: str, acq_date: str, radiopharm_time: str, acq_time: str) -> str:
    """计算两个时间点之间的差值（分钟）"""
    try:
        # 如果日期不同，返回error
        if radiopharm_date != acq_date:
            return 'error'
            
        radiopharm_seconds = time_to_seconds(radiopharm_time)
        acq_seconds = time_to_seconds(acq_time)
        
        # 计算时间差（秒）
        delta_seconds = acq_seconds - radiopharm_seconds
        
        # 如果时间差为负数（跨天），返回error
        if delta_seconds < 0:
            return 'error'
            
        # 转换为分钟并保留两位小数
        delta_minutes = delta_seconds / 60
        return f"{delta_minutes:.4f}"
    except Exception:
        return 'error'

def get_patient_info(header_file: Path) -> Optional[Dict]:
    """从DICOM header文件中提取患者信息"""
    try:
        with open(header_file, 'r', encoding='utf-8') as f:
            header_content = f.read().strip()
            if not header_content:
                logger.error(f"❌ header文件为空: {header_file}")
                return None
    except Exception as e:
        logger.error(f"❌ 读取header文件失败: {header_file}, 错误: {e}")
        return None

    try:
        # 初始化结果字典
        info = {
            'manufacturer_model': '',
            'patient_id': '',
            'name': '',
            'gender': '',
            'age': 0.0,
            'weight': 0.0,
            'size': 0.0,
            'acquisition_date': '',
            'acquisition_time': '',
            'frame_duration': 0.0,
            'total_dose': 0.0,
            'slice_thickness': 0.0,
            'rows': 0,
            'columns': 0,
            'pixel_spacing': 0.0,
            'radiopharmaceutical_date': '',
            'radiopharmaceutical_time': '',
            'series_description': '',
            'dfov': 0.0  # 新增DFOV字段
        }
        
        # Series Description提取模式
        series_desc_pattern = r'\(0008,\s*103e\).*?:\s*[\'"]?(.*?)[\'"]?$'
        
        # 定义标签映射
        tag_mapping = {
            '(0008, 1090)': ('manufacturer_model', lambda v: v),
            '(0010, 0020)': ('patient_id', lambda v: v),
            '(0010, 0010)': ('name', lambda v: v),
            '(0010, 0040)': ('gender', lambda v: v),
            '(0010, 1010)': ('age', extract_numeric_value),
            '(0010, 1030)': ('weight', extract_numeric_value),
            '(0010, 1020)': ('size', extract_numeric_value),
            '(0008, 0022)': ('acquisition_date', lambda v: v),
            '(0008, 0032)': ('acquisition_time', lambda v: v.split('.')[0] if '.' in v else v),
            '(0018, 1242)': ('frame_duration', lambda v: extract_numeric_value(v) / 60000),  # 转换为分钟
            '(0018, 1074)': ('total_dose', lambda v: extract_numeric_value(v) / 1000000),  # 转换为MBq
            '(0018, 0050)': ('slice_thickness', extract_numeric_value),
            '(0028, 0010)': ('rows', lambda v: int(extract_numeric_value(v))),
            '(0028, 0011)': ('columns', lambda v: int(extract_numeric_value(v))),
            '(0028, 0030)': ('pixel_spacing', lambda v: float(v.strip('[]').split(',')[0]) if re.search(r'\d', v) else 0.0),
            '(0018, 1078)': ('radiopharmaceutical_datetime', lambda v: parse_datetime(v)),
            '(0008, 103e)': ('series_description', lambda v: v),
            '(0018, 1100)': ('dfov', extract_dfov_value),  # Reconstruction Diameter
            '(0018, 9317)': ('dfov', extract_dfov_value)   # Reconstruction Field of View
        }
        
        # 解析每一行
        for line in header_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('Dataset.file_meta') or line.startswith('---'):
                continue
            
            # 专门处理Series Description
            series_match = re.search(series_desc_pattern, line)
            if series_match:
                info['series_description'] = series_match.group(1).strip()
                continue
                
            # 提取标签和值
            match = re.match(r'\((\d{4}),\s*(\d{4})\)\s+(.*?)\s+([^:]+):\s+(.*)', line)
            if not match:
                continue
                
            group, element = match.groups()[:2]
            tag = f"({group}, {element})"
            value = match.group(5).strip("'")  # 移除引号
            
            # 根据标签处理值
            if tag in tag_mapping:
                field, processor = tag_mapping[tag]
                if field == 'radiopharmaceutical_datetime':
                    # 特殊处理日期时间字段
                    date, time = processor(value)
                    info['radiopharmaceutical_date'] = date
                    info['radiopharmaceutical_time'] = time
                elif field == 'dfov':
                    # 特殊处理DFOV字段，只在当前值为0时更新（优先级处理）
                    if info['dfov'] == 0.0:
                        info[field] = processor(value)
                        logger.info(f"✅ 从标签 {tag} 提取DFOV值: {info[field]}")
                else:
                    info[field] = processor(value)
        
        return info
    except Exception as e:
        logger.error(f"❌ 解析header数据失败: {e}")
        return None

def format_excel_data(df: pd.DataFrame, string_columns: List[str]) -> pd.DataFrame:
    """格式化Excel数据，确保数据类型正确"""
    for col in string_columns:
        if col in df.columns:
            df[col] = df[col].astype(str)
            if col == 'patient_id':
                df[col] = df[col].str.zfill(8)
            elif col == 'id':
                df[col] = df[col].str.zfill(3)
            elif col.endswith('_date'):
                df[col] = df[col].str.zfill(8)
            elif col.endswith('_time') and not col == 'delta_time':
                df[col] = df[col].str.zfill(6)
    return df

# 新增：将单行数据保存为CSV（稳定串行追加）
def save_to_csv(data: Dict[str, Any], csv_file: Path, string_columns: List[str]) -> bool:
    """保存数据到CSV文件（稳定串行写入）"""
    try:
        # 确保目录存在
        Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)

        # 确保包含id键
        if 'id' not in data:
            logger.error("❌ 数据中缺少'id'字段")
            return False

        # 构造DataFrame并格式化
        new_df = pd.DataFrame([data])
        new_df = format_excel_data(new_df, string_columns)

        # 统一列顺序，缺失列补空
        for col in TABLE_COLUMNS:
            if col not in new_df.columns:
                new_df[col] = ''
        new_df = new_df[TABLE_COLUMNS]

        # 复制一份用于写出（对指定列做Excel文本包装）
        write_df = new_df.copy()
        for col in EXCEL_TEXT_COLUMNS:
            if col in write_df.columns:
                write_df[col] = write_df[col].map(wrap_excel_text)

        # 如果文件不存在，携带表头写入；否则追加不写表头
        is_new = not csv_file.exists()
        write_df.to_csv(
            csv_file,
            mode='a',
            header=is_new,
            index=False,
            encoding='utf-8-sig',
            na_rep=''  # 将缺失导出为空串，避免"NaN"
        )
        if is_new:
            logger.info(f"✅ 创建新的CSV文件: {csv_file}")
        else:
            logger.info(f"✅ 追加数据到CSV文件: {csv_file}")
        return True
    except Exception as e:
        logger.error(f"❌ 保存CSV数据失败: {e}")
        return False

def get_series_description(patient_id: str, modality: str, current_info: Dict) -> Tuple[str, str]:
    """获取MR和PET的系列描述"""
    mr_series = ""
    pet_series = ""

    # 先设置当前模态的描述（空串更稳定，避免被读取时当作缺失）
    if modality == 'pet':
        pet_series = current_info.get('series_description', "") or ""

        # 尝试获取MR系列描述
        mr_header_file = Path(config.MR_DIR) / patient_id / f"{patient_id}_mr.dcm.header"
        if mr_header_file.exists():
            try:
                mr_info = get_patient_info(mr_header_file)
                if mr_info and mr_info.get('series_description'):
                    mr_series = mr_info['series_description']
                    logger.info(f"📋 提取MR Series Description: {mr_series}")
            except Exception as e:
                logger.warning(f"⚠️ 读取MR Series Description失败: {e}")
    else:  # mr模态
        mr_series = current_info.get('series_description', "") or ""

        # 尝试获取PET系列描述
        pet_header_file = Path(config.PET_DIR) / patient_id / f"{patient_id}_pet.dcm.header"
        if pet_header_file.exists():
            try:
                pet_info = get_patient_info(pet_header_file)
                if pet_info and pet_info.get('series_description'):
                    pet_series = pet_info['series_description']
                    logger.info(f"📋 提取PET Series Description: {pet_series}")
            except Exception as e:
                logger.warning(f"⚠️ 读取PET Series Description失败: {e}")

    return mr_series, pet_series

def process_patient_info(patient_id: str, header_file: Path = None, modality: str = 'pet', existing_keys: Optional[set] = None) -> bool:
    """处理单个患者的信息

    参数:
        patient_id: 患者ID
        header_file: header文件路径，如果不指定则使用默认路径
        modality: 模态类型，'pet'或'mr'
        existing_keys: 已存在记录的键集合，用于去重，元素为(id, variant, modality)

    返回:
        处理成功返回True，否则返回False
    """
    try:
        logger.info(f"开始处理患者 {patient_id} 的{modality.upper()}信息")

        # 如果没有指定header文件，使用默认路径
        if header_file is None:
            header_file = Path(config.PET_DIR if modality == 'pet' else config.MR_DIR) / patient_id / f"{patient_id}_{modality}.dcm.header"

        if not header_file.exists():
            logger.warning(f"⚠️ 患者 {patient_id} 的{modality.upper()}头文件不存在: {header_file}")
            # 准备默认CSV数据
            excel_data = {
                'id': str(patient_id).zfill(3),
                'variant': "00",
                'manufacturer': "nofile",
                'patient_id': str(patient_id).zfill(8),
                'name': "nofile",
                'gender': "nofile",
                'age': 0.0,
                'weight': 0.0,
                'size': 0.0,
                'duration': 0.0 if modality == 'pet' else 'N/A',
                'dose': 0.0 if modality == 'pet' else 'N/A',
                'radiopharm_date': "00000000" if modality == 'pet' else 'N/A',
                'acq_date': "00000000",
                'radiopharm_time': "000000" if modality == 'pet' else 'N/A',
                'acq_time': "000000",
                'delta_time': "nofile" if modality == 'pet' else 'N/A',
                'thickness': 0.0,
                'rows': 0,
                'columns': 0,
                'pixel': 0.0,
                'dfov': 0.0,
                'diagnosis': '',
                'mr_series': "" if modality == 'mr' else '',
                'pet_series': "" if modality == 'pet' else '',
                'modality': modality.upper()
            }

            # 字符串列表
            string_columns = ['id', 'variant', 'patient_id', 'radiopharm_date', 'acq_date',
                              'radiopharm_time', 'acq_time', 'delta_time', 'mr_series',
                              'pet_series', 'modality']

            # 去重校验（如提供existing_keys）
            key = (excel_data['id'], excel_data['variant'], excel_data['modality'])
            if existing_keys is not None and key in existing_keys:
                logger.info(f"⏭️ 记录已存在，跳过: {key}")
                return True

            ok = save_to_csv(excel_data, PATIENT_DATA_INFO_CSV, string_columns)
            if ok and existing_keys is not None:
                existing_keys.add(key)
            return ok

        # 获取患者信息 
        info = get_patient_info(header_file)
        if not info:
            return False

        # 提取变体标识
        file_basename = os.path.basename(header_file)
        variant = extract_variant(file_basename)
        logger.info(f"📋 提取的变体标识: {variant} 从文件: {file_basename}")

        # 获取MR和PET系列描述
        mr_series, pet_series = get_series_description(patient_id, modality, info)

        # 准备时间数据
        acq_date = str(info.get('acquisition_date', '')).zfill(8)
        acq_time = str(info.get('acquisition_time', '')).zfill(6)

        # 根据不同模态准备不同的数据
        if modality == 'pet':
            radiopharm_date = str(info.get('radiopharmaceutical_date', '')).zfill(8)
            radiopharm_time = str(info.get('radiopharmaceutical_time', '')).zfill(6)
            delta_time = calculate_time_difference(radiopharm_date, acq_date, radiopharm_time, acq_time)
        else:
            radiopharm_date = 'N/A'
            radiopharm_time = 'N/A'
            delta_time = 'N/A'

        # 准备CSV数据
        excel_data = {
            'id': str(patient_id).zfill(3),
            'variant': variant,
            'manufacturer': info['manufacturer_model'],
            'patient_id': str(info['patient_id']).zfill(8),
            'name': info['name'],
            'gender': info['gender'],
            'age': info['age'],
            'weight': info['weight'],
            'size': info['size'],
            'duration': info.get('frame_duration', 'N/A') if modality == 'pet' else 'N/A',
            'dose': info.get('total_dose', 'N/A') if modality == 'pet' else 'N/A',
            'radiopharm_date': radiopharm_date,
            'acq_date': acq_date,
            'radiopharm_time': radiopharm_time,
            'acq_time': acq_time,
            'delta_time': delta_time,
            'thickness': info.get('slice_thickness', 0.0),
            'rows': info.get('rows', 0),
            'columns': info.get('columns', 0),
            'pixel': info.get('pixel_spacing', 0.0),
            'dfov': info.get('dfov', 0.0),
            'diagnosis': '',
            'mr_series': mr_series,
            'pet_series': pet_series,
            'modality': modality.upper()
        }

        # 字符串列表
        string_columns = ['id', 'variant', 'patient_id', 'radiopharm_date', 'acq_date',
                          'radiopharm_time', 'acq_time', 'delta_time', 'mr_series',
                          'pet_series', 'modality']

        # 去重校验（如提供existing_keys）
        key = (excel_data['id'], excel_data['variant'], excel_data['modality'])
        if existing_keys is not None and key in existing_keys:
            logger.info(f"⏭️ 记录已存在，跳过: {key}")
            return True

        ok = save_to_csv(excel_data, PATIENT_DATA_INFO_CSV, string_columns)
        if ok and existing_keys is not None:
            existing_keys.add(key)
        return ok
    except Exception as e:
        logger.error(f"❌ 处理患者 {patient_id} 信息失败: {e}")
        return False

def get_patient_info_for_ids(patient_ids: List[str], modality: str = 'pet') -> Dict[str, bool]:
    """获取指定ID列表患者的信息

    参数:
        patient_ids: 患者ID列表
        modality: 模态类型，'pet'或'mr'

    返回:
        包含处理结果的字典
    """
    results = {}
    success_count = 0

    logger.info(f"开始处理{len(patient_ids)}个患者的{modality.upper()}信息")

    # 启动时从CSV读取一次已有键集合用于去重（稳定性优先，避免频繁读写）
    existing_keys: set = set()
    try:
        if PATIENT_DATA_INFO_CSV.exists():
            df_existing = pd.read_csv(PATIENT_DATA_INFO_CSV, dtype=str, keep_default_na=False)
            # 清理可能的 ="..." 包装，标准化必要列
            for col in EXCEL_TEXT_COLUMNS:
                if col in df_existing.columns:
                    df_existing[col] = df_existing[col].map(unwrap_excel_text)
            if 'id' in df_existing.columns:
                df_existing['id'] = df_existing['id'].astype(str).str.zfill(3)
            if {'id', 'variant', 'modality'}.issubset(df_existing.columns):
                for row in df_existing[['id', 'variant', 'modality']].itertuples(index=False):
                    existing_keys.add((row[0], row[1], row[2]))
            logger.info(f"已载入现有记录 {len(existing_keys)} 条用于去重")
    except Exception as e:
        logger.warning(f"⚠️ 读取现有CSV用于去重失败: {e}")

    for patient_id in patient_ids:
        try:
            # 查找该患者的所有header文件
            patient_dir = Path(config.PET_DIR if modality == 'pet' else config.MR_DIR) / patient_id
            pattern = f"{patient_id}_{modality}*.dcm.header"

            logger.info(f"查找患者 {patient_id} 的{modality.upper()}文件: {patient_dir}/{pattern}")

            if not patient_dir.exists():
                logger.warning(f"⚠️ 患者 {patient_id} 的{modality.upper()}目录不存在")
                results[patient_id] = False
                continue

            # 获取所有header文件
            header_files = list(patient_dir.glob(pattern))

            if not header_files:
                logger.warning(f"⚠️ 患者 {patient_id} 没有找到{modality.upper()}的header文件")
                results[patient_id] = False
                continue

            # 处理每个header文件（串行，稳定）
            success = False
            for header_file in header_files:
                try:
                    file_success = process_patient_info(patient_id, header_file, modality, existing_keys)
                    success = success or file_success
                    if file_success:
                        success_count += 1
                except Exception as e:
                    logger.error(f"❌ 处理患者 {patient_id} 的header文件 {header_file} 时出错: {e}")
                    # 继续处理其他header文件

            results[patient_id] = success
        except Exception as e:
            logger.error(f"❌ 处理患者 {patient_id} 时出错: {e}")
            results[patient_id] = False
            # 继续处理其他患者

    # 统计结果
    total = len(patient_ids)

    logger.info(f"🎉 {modality.upper()}信息获取完成，患者总计: {total}个，成功处理的患者: {sum(1 for success in results.values() if success)}个")
    logger.info(f"🎉 总共处理的变体文件: {success_count}个")

    if success_count > 0:
        logger.info(f"✅ 患者信息已保存到: {PATIENT_DATA_INFO_CSV}")

    return results 