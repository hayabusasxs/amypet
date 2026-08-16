import os
import pydicom

# 设置起始和结束的文件夹编号范围
START_NUM = 1
END_NUM = 40

# 设置根目录
ROOT_DIR = os.path.expanduser('~/AV45/pet')  # 根据你的实际路径修改

# 遍历指定范围的文件夹
for i in range(START_NUM, END_NUM + 1):
    # 构造文件夹路径
    folder_path = os.path.join(ROOT_DIR, f"{i:03d}")
    
    # 检查文件夹是否存在
    if os.path.isdir(folder_path):
        print(f"Processing folder: {folder_path}")
        
        # 获取该文件夹下的子文件夹（假设每个文件夹只有一个子文件夹）
        subfolders = [f.path for f in os.scandir(folder_path) if f.is_dir()]
        
        if subfolders:
            # 获取子文件夹中的第一个 DICOM 文件
            dicom_folder = subfolders[0]
            dicom_files = [f for f in os.listdir(dicom_folder) if f.endswith('.dcm')]
            
            if dicom_files:
                first_dcm_file = os.path.join(dicom_folder, dicom_files[0])
                
                # 读取 DICOM 文件的头信息
                dicom_data = pydicom.dcmread(first_dcm_file)
                
                # 将头信息保存为纯文本文件
                header_file = os.path.join(folder_path, f"{i:03d}.pet.dcm.header")
                
                with open(header_file, 'w') as f:
                    f.write(str(dicom_data))  # 将 DICOM 数据转换为文本并写入文件

                print(f"Header saved as {header_file}")
            else:
                print(f"No DICOM files found in {dicom_folder}")
        else:
            print(f"No subfolders found in {folder_path}")
    else:
        print(f"Folder {folder_path} does not exist.")

print("Processing completed.")
