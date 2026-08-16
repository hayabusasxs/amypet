# 文件结构目录
```/path/to/amypet
├── data		            //存放患者信息、dcm图像以及处理后的图像
│   ├── data.info.xlsx		//患者信息
│   ├── mr		            //原始mr dcm和nii.gz图像以及header信息
│   │   └── 001
│   │       ├── 001_mr					   //患者原始mr dcm文件夹，外界拷贝至此
│   │       ├── 001_mr.dcm.header		//原始mr dcm的header
│   │       ├── 001_mr.json			   //mri2niix生成的BIDS sidecar
│   │       ├── 001_mr.nii.gz			   //dcm2niix生成
│   │       └── 001_mr.nii.gz.header	//.nii.gz的header
│   ├── pet	            /原始pet dcm和nii.gz图像以及header信息
│   │   ├── 001_pet					   //患者原始pet dcm文件夹，外界拷贝至此
│   │   ├── 001_pet-1					//患者重建后pet dcm文件夹，外界拷贝至此
│   │   ├── 001_pet-2					//患者重建后pet dcm文件夹，外界拷贝至此
│   │   ├── 001_pet.dcm.header		//原始mr dcm的header
│   │   ├── 001_pet-1.dcm.header		//患者重建后pet dcm文件夹，外界拷贝至此
│   │   ├── 001_pet-2.dcm.header		//患者重建后pet dcm文件夹，外界拷贝至此
│   │   ├── 001_pet.json				//mri2niix生成的BIDS sidecar
│   │   ├── 001_pet.nii.gz				//dcm2niix生成
│   │   └── 001_pet.nii.gz.header	//.nii.gz的header,只需要1个
│   └── recon               //freesurfer的$SUBJECTS_DIR
│       └── 001
│           ├── label		                         //recon-all自动生成
│           ├── mri		                            //recon-all自动生成
│           ├── mask		                            //制作mask时的存放位置
│           ├── pet		                            //存放配准后的pet本体以及变体
│           │    ├── 001_PET
│           │    │      ├── 001_pet.mgz             //原始pet的mgz格式
│           │    │      ├── registered_pet.mgz      //配准到个体mr空间pet
│           │    │      ├── registered_pet.nii.gz   //配准到个体mr空间pet
│           │    │      ├── pet2mri.lta             //配准到个体mr空间pet的转换矩阵
│           │    │      └── pet2mri.dat             //配准到个体mr空间pet的转换矩阵
│           │    ├── 001_PET-1
│           │    └── 001_PET-2
│           ├── scripts	                            //recon-all自动生成
│           ├── stats		                         //recon-all自动生成，以及后续对pet进行定量计算的结果
│           ├── surf		                            //recon-all自动生成
│           ├── tmp		                            //recon-all自动生成
│           ├── touch		                         //recon-all自动生成
│           └── trash		                         //recon-all自动生成
├── help		            //存放一些指令的manual
├── sh			            //存放批处理sh或py
│   ├── amypet_calc                      //存放pet配准、mask制作和提取计算相关脚本
│   │   └── regis_mask_extract_calc.sh   //完成pet配准、mask制作、提取pet ROI内平均值及SUVr计算
│   ├── header_extract                   //header的提取，以及dcm2niix
│   │   ├── dcm_mr_header.py             //提取mr dcm文件的header
│   │   ├── dcm_pet_header.py            //提取pet dcm文件的header
│   │   ├── nifti_mr_header.sh           //提取mr nifti文件的header
│   │   ├── nifti_pet_header.sh          //提取pet nifti文件的header
│   │   └── delete_header.sh             //删除某个受试者文件夹下的header文件
│   └── recon-all           //FreeSurfer处理相关脚本
│       ├── recon-all_time_extract.sh               //提取recon-all处理时间
│       ├── recon-all_zsh_setRange.sh               //基础版重建脚本
│       ├── recon-all_zsh_setRange_parallel.sh      //并行处理版本
│       └── recon-all_zsh_setRange_single_8core.sh  //单受试者8核心处理
└── workflow.md
```
# dcm2niix时的选项：
- output filename: %f
- output directory: save nifti images to the same folder as DICOM
- output format: .nii.gz (compressed NifTi)
- creat BIDS sidecar: yes, with personal identifiers

# 程序处理步骤
1. 设置要处理患者的序号范围，如001～012，或者指定几个受试者，如012, 015等。这些序号的范围会贯穿程序始终，暂记为"pRange"。
2. pRange内dcm到nii格式转换：按照dcm2niix选项要求，将pRange内的/mr/00x和/pet/00x内dcm转换为niix并保存在/mr/00x或者/pet/00x文件夹内。
3. 提取相应header并保存在/mr/00x或者/pet/00x文件夹内。
4. 对pRange范围内受试者执行recon-all。
5. 执行pet到mr个体空间转换矩阵获取、pet配准到mr个体空间、mask的制作、使用mask提取pet ROI内平均值、SUVr的计算。
6. 附加内容：
    1. 一个受试者存在1个mr序列，但可能存在多个使用相同pet原始数据重建的序列。不同重建方法命名的序列分别为00x_PET-1.nii.gz、00x-PET-2.nii.gz等。因此在使用自动脚本识别pet文件时要注意这个问题。但在生成每个00x_PET-1.nii.gz的定量结果时，要备注好是-1还是-2.
  
# 程序文件树
```
/amypet
├── config.py               # 全局配置文件
├── main.py                 # 主程序入口（支持convert,header,recon,register,mask步骤）
├── modules/                # 功能模块
│   ├── __init__.py         # 模块导出
│   ├── dcm_converter.py    # DICOM转换功能（完成）
│   ├── header_extractor.py # 提取header功能（完成）
│   ├── recon_processor.py  # FreeSurfer处理功能（完成）
│   ├── registration.py     # 图像配准功能（完成，支持多种PET变体）
│   ├── mask_processor.py   # 制作掩膜功能（完成，包括靶区掩膜和参考区掩膜）
│   ├── suvr_calculator.py  # 计算SUVr值（完成）
│   └── utils.py            # 通用工具函数（完成）
└── data/                   # 数据目录
    ├── mr/                 # MR数据目录
    ├── pet/                # PET数据目录
    └── recon/              # FreeSurfer重建目录（对应$SUBJECTS_DIR）
```

# AMYPET 项目介绍与使用指南

## 项目概述

AMYPET 是一个用于 PET-MRI 神经影像数据处理的自动化工具链，专为淀粉样蛋白 PET 成像数据分析设计。该工具链集成了从 DICOM 格式转换、图像配准到 SUVr 计算的全流程处理，支持批量处理多个受试者数据，并能够处理同一患者的多个 PET 变体重建数据。

### 主要功能

- DICOM 到 NIfTI 格式转换
- DICOM 和 NIfTI 头文件提取
- FreeSurfer 结构重建
- PET 到 MRI 空间的图像配准
- 目标区域和参考区域掩膜制作
- SUVr 计算与定量分析
- 患者信息提取与管理
- 文件管理（删除非必要文件）

## 使用指南

### 安装与依赖

本项目依赖以下工具和库：
- Python 3.6+
- FreeSurfer 7.0+
- dcm2niix
- pandas, numpy, nibabel 等 Python 库

确保已正确设置 FreeSurfer 环境变量：
```bash
export FREESURFER_HOME=/path/to/freesurfer
source $FREESURFER_HOME/SetUpFreeSurfer.sh
```

### 基本用法

AMYPET 使用命令行界面操作，基本命令格式如下：
```bash
python main.py -r <范围> -s <步骤> [选项]
```

或者

```bash
python main.py -i <ID列表> -s <步骤> [选项]
```

### 命令行参数

| 参数 | 描述 |
|-----|------|
| `-r`, `--range` | 指定患者范围，如 "1-10" |
| `-i`, `--ids` | 指定患者 ID 列表，如 "001,003,005" |
| `-s`, `--steps` | 指定处理步骤，如 'rename', 'convert', 'header', 'info', 'recon', 'register', 'mask', 'suvr', 'delete' |
| `-m`, `--modality` | 指定处理模态，可选值：mr, pet, both (默认: both) |
| `-w`, `--workers` | 指定并行处理数，默认为 8 |
| `-f`, `--fs-flags` | 传递给 FreeSurfer recon-all 的额外参数 |
| `--force` | 强制执行，不提示确认 |
| `--keep-nifti` | 删除文件时保留 .nii.gz 文件 |

### 处理步骤详解

#### 1. 目录重命名 (rename)

将原始数据目录重命名为标准格式。

```bash
python main.py -r 1-10 -s rename
```

#### 2. DICOM 转换 (convert)

将 DICOM 文件转换为 NIfTI 格式。

```bash
python main.py -r 1-10 -s convert
```

参数说明：
- `-m mr`: 仅处理 MR 数据
- `-m pet`: 仅处理 PET 数据

#### 3. 头文件提取 (header)

提取 DICOM 和 NIfTI 文件的头信息。

```bash
python main.py -r 1-10 -s header
```

删除已提取的头文件：
```bash
python main.py -r 1-10 -s header --delete
```

#### 4. 患者信息提取 (info)

从 DICOM 头文件中提取患者相关信息并保存到 Excel。

```bash
python main.py -r 1-10 -s info
```

#### 5. FreeSurfer 重建 (recon)

使用 FreeSurfer 处理 MRI 数据。

```bash
python main.py -r 1-10 -s recon -w 10
```

参数说明：
- `-w 10`: 使用 10 个并行任务
- `-f "-parallel -qcache"`: 传递额外参数给 FreeSurfer

#### 6. 图像配准 (register)

将 PET 图像配准到对应的 MRI 空间。

```bash
python main.py -r 1-10 -s register
```

#### 7. 掩膜制作 (mask)

创建用于 SUVr 计算的靶区和参考区掩膜。

```bash
python main.py -r 1-10 -s mask
```

#### 8. SUVr 计算 (suvr)

计算标准摄取值比。

```bash
python main.py -r 1-10 -s suvr
```

#### 9. 文件清理 (delete)

删除目录中非必要文件。默认删除除文件夹外的所有文件，可选择保留 .nii.gz 文件。

```bash
# 删除所有文件（除文件夹外）
python main.py -r 1-10 -s delete

# 仅删除非 .nii.gz 文件
python main.py -r 1-10 -s delete --keep-nifti
```

### 组合步骤

您可以组合多个步骤一次性执行：

```bash
# 执行连续多个步骤
python main.py -r 1-10 -s convert,header,recon

# 执行所有标准步骤（不包括 delete）
python main.py -r 1-10 -s all

# 执行所有步骤（包括 delete）
python main.py -r 1-10 -s all,delete --keep-nifti
```

### 常见使用场景

#### 新患者完整处理流程

```bash
python main.py -i 001 -s all -w 10
```

#### 处理新添加的 PET 变体

对于已经完成 MR 处理的患者，添加新的 PET 变体后：

```bash
python main.py -i 001 -s header,info,register,suvr -m pet
```

#### 批量处理特定步骤

```bash
# 批量提取患者信息
python main.py -r 1-50 -s info

# 批量清理文件，保留 .nii.gz
python main.py -r 1-50 -s delete --keep-nifti
```

### 输出结果

处理完成后，各类结果将保存在以下位置：

- 转换后的 NIfTI 文件：`data/mr/00x/` 和 `data/pet/00x/`
- FreeSurfer 重建结果：`data/recon/00x/`
- 配准后的 PET 图像：`data/recon/00x/pet/00x_PET/`
- 掩膜文件：`data/recon/00x/mask/`
- SUVr 计算结果：`data/recon/00x/stats/`
- 患者信息：`data/patient_data_info.xlsx`

### 注意事项

1. 患者 ID 在整个系统中使用三位数格式（如 001、002）
2. 一个患者可以有多个 PET 变体，命名格式为 `00x_pet-变体标识`
3. 删除操作具有破坏性，请谨慎使用，考虑使用 `--keep-nifti` 保留重要文件
4. 设置并行任务数时，建议不超过系统逻辑处理器数量

## 故障排查

### 常见问题

1. **FreeSurfer 错误**：确保 FreeSurfer 环境变量正确设置
   ```bash
   echo $FREESURFER_HOME
   source $FREESURFER_HOME/SetUpFreeSurfer.sh
   ```

2. **dcm2niix 错误**：检查 dcm2niix 是否正确安装并可在 PATH 中找到
   ```bash
   which dcm2niix
   ```

3. **内存不足**：减小并行处理数量
   ```bash
   python main.py -r 1-5 -s recon -w 4
   ```

### 日志文件

所有处理日志保存在 `logs/python_proc/` 目录下，命名格式为 `amypet_processing_YYYYMMDD-HHMMSS.log`。出现问题时请查阅相应日志文件。


