#!/bin/bash
# 双击这个文件即可查看。静态包必须走 http 打开 ——
# file:// 协议下浏览器会以跨域为由拒绝读取 api/ 下的 JSON。
cd "$(dirname "$0")" || exit 1
echo "工作台静态快照 → http://127.0.0.1:18899/"
echo "（关掉这个终端窗口就停止）"
sleep 1 && open "http://127.0.0.1:18899/" &
/usr/bin/python3 serve.py
