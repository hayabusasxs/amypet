#!/bin/zsh
#开始之前修改：开始/结束范围，根目录，生成的文件后缀（mr或pet）
# 设置起始和结束的文件夹编号范围
START_NUM=1
END_NUM=40

# 设置根目录
ROOT_DIR="$HOME/AV45/pet"  # 根据你的实际路径修改

# 遍历指定范围的文件夹
for i in $(seq -f "%03g" $START_NUM $END_NUM); do
  # 构造文件夹路径
  FOLDER_PATH="$ROOT_DIR/$i"
  
  # 检查文件夹是否存在
  if [ -d "$FOLDER_PATH" ]; then
    echo "Processing folder: $FOLDER_PATH"
    
    # 遍历该文件夹下所有的 .nii.gz 文件
    for nii_file in "$FOLDER_PATH"/*.nii.gz; do
      if [ -f "$nii_file" ]; then
        # 提取文件夹名
        FOLDER_NAME=$(basename "$FOLDER_PATH")
        
        # 获取文件名（不带扩展名）
        NII_NAME=$(basename "$nii_file" .nii.gz)
        
        # 设置输出文件路径
        HEADER_FILE="$FOLDER_PATH/$FOLDER_NAME.pet.nii.gz.header"
        
        # 执行 fslhd 并保存结果
        echo "Running fslhd for $nii_file and saving to $HEADER_FILE"
        fslhd "$nii_file" > "$HEADER_FILE"
        
        echo "Header saved as $HEADER_FILE"
      fi
    done
  else
    echo "Warning: Folder $FOLDER_PATH does not exist."
  fi
done

echo "Processing completed."
