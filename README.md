# AMYPET 神经影像处理系统

AMYPET 是一个专为 **PET-MRI 神经影像数据处理** 设计的高效自动化命令行工具集（特别适用于淀粉样蛋白 Amyloid-PET 成像）。系统支持从 DICOM 格式转换、头文件提取、FreeSurfer 结构重建、PET-MRI 图像配准、掩膜制作到 SUVr 定量计算与 PVC 校正的全流程处理。

---

## 🌟 核心特性

- **端到端自动化流水线**：涵盖 DICOM 转换、Header 提取、FreeSurfer 重建、配准、Mask 提取、SUVr 计算及 PVC（部分容积效应校正）全流程。
- **多变体支持**：支持单个患者多组 PET 重建参数（如不同时长、不同滤波条件）的批量处理与变体管理。
- **高效批处理调度**：支持按患者 ID 列表或范围批量处理，灵活指定多进程/多线程并行度。
- **质量检查（QC）**：集成基于 Freeview 与 Tkregister 的一键可视化检查（分割、配准、掩膜与融合图像）。
- **硬件自适应**：智能检测 Apple Silicon / 多核 CPU 架构，自适应调整并行处理线程。

---

## 🛠️ 系统环境要求

- **操作系统**：macOS (推荐) / Linux
- **Python**：Python 3.8+
- **神经影像外部依赖**：
  - [FreeSurfer](https://surfer.nmr.mgh.harvard.edu/fswiki/DownloadAndInstall) 7.x / 8.x
  - [FSL](https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FslInstallation) 6.0+
  - [dcm2niix](https://github.com/rordenlab/dcm2niix#install)

---

## 📦 安装指南

### 1. 克隆代码仓库
```bash
git clone https://github.com/hayabusasxs/amypet.git
cd amypet
```

### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3. 环境配置
请确保 FreeSurfer 和 FSL 已在你的 Shell 配置文件（如 `~/.zshrc` 或 `~/.bashrc`）中正确配置环境变量：
```bash
# FreeSurfer 配置示例
export FREESURFER_HOME=/path/to/freesurfer
source $FREESURFER_HOME/SetUpFreeSurfer.sh

# FSL 配置示例
export FSLDIR=/path/to/fsl
source ${FSLDIR}/etc/fslconf/fsl.sh
export PATH=${FSLDIR}/bin:${PATH}
```

---

## 🚀 快速上手

### 1. 数据目录结构
在项目根目录或指定数据目录下放置受试者数据（支持通过环境变量 `AMYPET_DATA_ROOT` 指定路径）：
```text
amypet/
├── data/
│   ├── mr/
│   │   └── 001/                 # 患者 001 的 MR DICOM 文件夹
│   ├── pet/
│   │   └── 001/                 # 患者 001 的 PET DICOM 文件夹
│   └── patient_data_info.template.csv  # 患者元数据模板
├── config.py                    # 集中配置文件
└── main.py                      # CLI 主程序入口
```

---

### 2. 常用命令行示例

* **单步处理（按患者 ID 列表）**：
  ```bash
  python main.py -i 001,002 -s convert -m both
  ```

* **批量多步连续处理（按患者范围）**：
  ```bash
  python main.py -r 1-10 -s convert,header,recon -m both -w 8
  ```

* **执行全流程处理（convert -> header -> recon -> registrate -> mask -> suvr）**：
  ```bash
  python main.py -i 001 -s all -w 10
  ```

* **结果检查与质控（QC）**：
  ```bash
  # 检查 001 号患者的配准效果
  python main.py -i 001 -rc

  # 检查分割结果
  python main.py -i 001 -sc

  # 全面质控检查（包含 MR 分割、PET 配准、掩膜及融合）
  python main.py -i 001 -ac
  ```

---

## 📋 命令行参数汇总

| 参数 (短/长) | 说明 | 示例 |
| :--- | :--- | :--- |
| `-i`, `--ids` | 指定受试者编号列表（逗号分隔） | `-i 001,002,005` |
| `-r`, `--range` | 指定受试者编号范围 | `-r 1-10` |
| `-s`, `--steps` | 指定执行步骤，可选：`rename`, `convert`, `header`, `info`, `recon`, `registrate`, `mask`, `suvr`, `pvc`, `pvc_suvr`, `delete`, `all` | `-s convert,header` |
| `-m`, `--modality` | 指定模态：`mr`, `pet`, `both` (默认: `both`) | `-m pet` |
| `-w`, `--workers` | 最大并行进程/线程数 (默认: 8/10) | `-w 4` |
| `-f`, `--fs-flags` | 传递给 FreeSurfer `recon-all` 的额外标志 | `-f "-parallel -openmp 8"` |
| `--keep-nifti` | 使用 delete 步骤清理时保留 `.nii.gz` 文件 | `--keep-nifti` |
| `-sc` / `-rc` / `-mc` / `-ac` | 质控检查：分割 / 配准 / 掩膜 / 全面检查 | `-i 001 -ac` |

---

## 📂 核心模块架构

* `modules/`：
  * `dcm_converter.py`：DICOM 转 NIfTI 工具。
  * `header_extractor.py`：影像头文件信息提取。
  * `recon_processor.py`：FreeSurfer 脑结构重建流水线。
  * `registration.py`：PET-MRI 刚体配准与矩阵计算。
  * `mask_processor.py`：靶区与参考区（小脑/脑桥等）掩膜构建。
  * `suvr_calculator.py`：SUVr 标化摄取值比率计算。
  * `pet_pvc_processor.py` & `pvc_suvr_calculator.py`：部分容积效应校正 (GTM-PVC)。
  * `check.py`：可视化质量评估。
* `sh/`：自动化批处理辅助脚本。

---

## 📄 许可协议

本项目采用 [MIT License](LICENSE) 授权许可。

Copyright (c) 2025 hayabusasxs. All Rights Reserved.
