#!/bin/bash

# Pity前端自动部署脚本
# 功能：构建前端并将产物同步到后端statics目录

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 项目路径
FRONTEND_DIR="/Users/zhanzhicai/Desktop/py/AIFullStackTesting/frontend"
BACKEND_STATIC_DIR="/Users/zhanzhicai/Desktop/py/AIFullStackTesting/backend/statics"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Pity前端自动部署脚本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查前端目录
if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}错误: 前端目录不存在 $FRONTEND_DIR${NC}"
    exit 1
fi

# 进入前端目录
cd "$FRONTEND_DIR" || exit 1

# 询问是否需要安装依赖
echo -e "${BLUE}是否需要安装/更新依赖？(y/n)${NC}"
read -r install_deps

if [ "$install_deps" = "y" ] || [ "$install_deps" = "Y" ]; then
    echo -e "${GREEN}正在安装依赖...${NC}"
    npm install
    if [ $? -ne 0 ]; then
        echo -e "${RED}依赖安装失败！${NC}"
        exit 1
    fi
    echo -e "${GREEN}依赖安装完成！${NC}"
    echo ""
fi

# 构建前端
echo -e "${GREEN}正在构建前端...${NC}"
npm run build

if [ $? -ne 0 ]; then
    echo -e "${RED}前端构建失败！${NC}"
    exit 1
fi

echo -e "${GREEN}前端构建完成！${NC}"
echo ""

# 检查构建产物
if [ ! -d "dist" ]; then
    echo -e "${RED}错误: 构建产物dist目录不存在${NC}"
    exit 1
fi

# 清空后端statics目录
echo -e "${GREEN}正在清空后端statics目录...${NC}"
rm -rf "${BACKEND_STATIC_DIR:?}"/*
if [ $? -ne 0 ]; then
    echo -e "${RED}清空statics目录失败！${NC}"
    exit 1
fi

# 复制构建产物
echo -e "${GREEN}正在复制构建产物到后端...${NC}"
cp -r dist/* "$BACKEND_STATIC_DIR/"

if [ $? -ne 0 ]; then
    echo -e "${RED}复制文件失败！${NC}"
    exit 1
fi

echo -e "${GREEN}文件复制完成！${NC}"
echo ""

# 显示部署信息
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}部署成功！${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "前端构建产物已复制到: ${GREEN}${BACKEND_STATIC_DIR}${NC}"
echo ""
echo -e "下一步操作："
echo -e "1. 启动后端服务: ${GREEN}cd ${BACKEND_STATIC_DIR}/.. && python main.py${NC}"
echo -e "2. 访问应用: ${GREEN}http://localhost:7777${NC}"
echo ""

# 询问是否启动后端
echo -e "${BLUE}是否启动后端服务？(y/n)${NC}"
read -r start_backend

if [ "$start_backend" = "y" ] || [ "$start_backend" = "Y" ]; then
    cd "$BACKEND_STATIC_DIR/.." || exit 1
    echo -e "${GREEN}正在启动后端服务...${NC}"
    python main.py
fi