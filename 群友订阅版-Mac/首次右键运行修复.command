#!/bin/zsh
set -e

cd "$(dirname "$0")"
PACKAGE_DIR="$(pwd)"

echo "正在修复 Mac 首次运行权限..."
echo "当前文件夹：$PACKAGE_DIR"
echo

xattr -dr com.apple.quarantine "$PACKAGE_DIR" 2>/dev/null || true
chmod +x "$PACKAGE_DIR/WEEX交易所/WEEX交易所.command"

echo "修复完成。"
echo
echo "现在可以双击：WEEX交易所/WEEX交易所.command"
echo
echo "按任意键关闭窗口..."
read -k 1
