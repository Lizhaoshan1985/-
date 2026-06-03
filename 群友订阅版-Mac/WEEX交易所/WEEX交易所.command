#!/bin/zsh
set -e

cd "$(dirname "$0")"

export PYTHONDONTWRITEBYTECODE=1

echo "正在启动 WEEX 交易所跟单..."
echo

load_homebrew() {
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif [ -x /opt/homebrew/bin/python3 ]; then
    echo "/opt/homebrew/bin/python3"
  elif [ -x /usr/local/bin/python3 ]; then
    echo "/usr/local/bin/python3"
  fi
}

load_homebrew

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(find_python)"
else
  if ! command -v brew >/dev/null 2>&1; then
    echo "未检测到 Homebrew，正在自动安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    load_homebrew
  fi

  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew 安装后仍未检测到 brew，请关闭窗口后重新双击本文件。"
    echo "按任意键关闭窗口..."
    read -k 1
    exit 1
  fi

  echo "未检测到 Python，正在通过 Homebrew 自动安装 Python..."
  brew install python
  load_homebrew
  PYTHON_BIN="$(find_python)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 安装完成但暂时未找到 python3。"
  echo "请关闭窗口后重新双击 WEEX交易所.command。"
  echo "按任意键关闭窗口..."
  read -k 1
  exit 1
fi

"$PYTHON_BIN" -u WEEX交易所.py
echo
echo "程序已退出，按任意键关闭窗口..."
read -k 1
