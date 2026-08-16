#!/bin/zsh

# 输出表格的文件路径
output_file="./recon-all_time"

# 如果表格不存在，则创建表头
if [[ ! -f "$output_file" ]]; then
  echo "name;recon-all-run-time-hours;error" > "$output_file"
fi

# 工作目录路径前缀
base_dir="${SUBJECTS_DIR:-$HOME/amypet/data/recon}"

# 遍历指定范围内的文件夹（001 到 020）
for folder in {037..040}; do
  # 拼接出 recon-all.log 的完整路径
  log_file="${base_dir}/${folder}/scripts/recon-all.log"

  # 打印完整路径，确认路径拼接正确
  echo "Checking log file at: $log_file"  # 调试信息，确认路径是否正确

  # 检查 log 文件是否存在
  if [[ -f "$log_file" ]]; then
    echo "Processing log file: $log_file"  # 调试信息，确认正在处理的文件

    # 提取 recon-all-run-time-hours 后的数字部分
    runtime=$(ggrep -oP "(?<=#@#%# recon-all-run-time-hours )\d+\.\d+" "$log_file")
    if [[ -z "$runtime" ]]; then
      echo "Warning: recon-all-run-time-hours not found in $log_file"  # 调试信息
    fi

    # 提取 finished without error 信息
    error_status=$(grep "recon-all -s" "$log_file" | grep -o "finished without error")
    if [[ -z "$error_status" ]]; then
      echo "Warning: finished without error not found in $log_file"  # 调试信息
    fi
    
    # 判断是否有错误
    if [[ -n "$error_status" ]]; then
      error_code=0  # without error
    else
      error_code=1  # with error
    fi

    # 获取当前文件夹名称
    folder_name=$folder

    # 如果 runtime 和 error_code 都有效，则将数据写入文件
    if [[ -n "$runtime" && -n "$error_code" ]]; then
      echo "$folder_name;$runtime;$error_code" >> "$output_file"
    else
      echo "Warning: Skipping folder $folder_name due to missing data"  # 调试信息
    fi
  else
    echo "Warning: Log file not found in $folder"  # 调试信息，输出未找到的日志文件路径
  fi
done

echo "Data has been recorded to $output_file"
