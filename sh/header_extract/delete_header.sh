#!/bin/zsh

# 设置起始和结束的文件夹编号范围
START_NUM=1
END_NUM=40

# 设置根目录
ROOT_DIR="$HOME/AV45/mr"  # 根据你的实际路径修改

# 创建一个临时列表，用来保存所有找到的 header 文件
header_files=()

# 使得通配符表达式没有匹配文件时不会抛出错误
setopt nullglob

# 遍历指定范围的文件夹
for i in $(seq -f "%03g" $START_NUM $END_NUM); do
  # 构造文件夹路径
  FOLDER_PATH="$ROOT_DIR/$i"
  
  # 检查文件夹是否存在
  if [ -d "$FOLDER_PATH" ]; then
    echo "Checking folder: $FOLDER_PATH"
    
    # 遍历该文件夹下所有的 .header 文件，包括隐藏的 .header 文件
    found_files=false  # 标志：检查是否找到文件
    for header_file in "$FOLDER_PATH"/.*.header "$FOLDER_PATH"/*.header; do
      if [ -f "$header_file" ]; then
        # 将找到的文件加入列表
        header_files+=("$header_file")
        found_files=true
      fi
    done

    # 如果没有找到文件，继续检查下一个文件夹
    if [ "$found_files" = false ]; then
      echo "No header files found in $FOLDER_PATH"
    fi

  else
    echo "Warning: Folder $FOLDER_PATH does not exist."
  fi
done

# 如果找到了 header 文件，列出它们并进行确认
if [ ${#header_files[@]} -gt 0 ]; then
  echo "The following header files were found:"
  
  # 列出所有找到的 header 文件
  for file in "${header_files[@]}"; do
    echo "$file"
  done

  # 提示用户是否删除所有文件
  echo "Do you want to delete these files? (y/n): "
  read response

  if [[ "$response" == "y" || "$response" == "Y" ]]; then
    # 删除所有找到的文件
    for file in "${header_files[@]}"; do
      rm "$file"
      echo "Deleted: $file"
    done
  else
    echo "No files were deleted."
  fi
else
  echo "No header files found."
fi

echo "Processing completed."
