#!/bin/bash

# =============================================================================
# 网格交易机器人 - 实盘启动脚本
# =============================================================================
# 功能：在VPS上启动网格交易策略，后台持续运行
# 使用：./start_live_trading.sh
# =============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目配置
PROJECT_NAME="GirdBot_BN"
PYTHON_SCRIPT="start_grid_bot.py"
PID_FILE="grid_bot.pid"
LOG_DIR="log"
SCREEN_SESSION="grid_trading"

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] ${message}${NC}"
}

# 检查是否已经在运行
check_if_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            print_message $YELLOW "策略已在运行中 (PID: $pid)"
            print_message $BLUE "使用 './view_logs.sh' 查看运行状态"
            print_message $BLUE "使用 './stop_trading.sh' 停止策略"
            exit 1
        else
            print_message $YELLOW "发现过期的PID文件，正在清理..."
            rm -f "$PID_FILE"
        fi
    fi
}

# 检查依赖
check_dependencies() {
    print_message $BLUE "检查运行环境..."
    
    # 检查Python
    if ! command -v python3 &> /dev/null; then
        print_message $RED "错误: 未找到 python3"
        exit 1
    fi
    
    # 检查screen
    if ! command -v screen &> /dev/null; then
        print_message $YELLOW "警告: 未找到 screen，正在安装..."
        sudo apt-get update && sudo apt-get install -y screen
    fi
    
    # 检查项目文件
    if [ ! -f "$PYTHON_SCRIPT" ]; then
        print_message $RED "错误: 未找到 $PYTHON_SCRIPT"
        exit 1
    fi
    
    # 检查配置文件
    if [ ! -f "config.py" ]; then
        print_message $RED "错误: 未找到 config.py 配置文件"
        exit 1
    fi
    
    # 检查日志目录
    if [ ! -d "$LOG_DIR" ]; then
        print_message $BLUE "创建日志目录: $LOG_DIR"
        mkdir -p "$LOG_DIR"
    fi
    
    print_message $GREEN "环境检查完成"
}

# 安装Python依赖
install_dependencies() {
    if [ -f "requirements.txt" ]; then
        print_message $BLUE "检查Python依赖..."
        pip3 install -r requirements.txt --quiet
        print_message $GREEN "依赖检查完成"
    fi
}

# 启动策略
start_strategy() {
    print_message $BLUE "启动网格交易策略..."
    
    # 使用screen在后台运行
    screen -dmS "$SCREEN_SESSION" bash -c "
        cd $(pwd)
        python3 $PYTHON_SCRIPT 2>&1 | tee -a $LOG_DIR/live_trading.log
    "
    
    # 等待一下确保启动
    sleep 3
    
    # 获取screen会话中的进程PID
    local screen_pid=$(screen -list | grep "$SCREEN_SESSION" | awk '{print $1}' | cut -d'.' -f1)
    
    if [ -n "$screen_pid" ]; then
        echo "$screen_pid" > "$PID_FILE"
        print_message $GREEN "策略启动成功!"
        print_message $GREEN "Screen会话: $SCREEN_SESSION (PID: $screen_pid)"
        print_message $BLUE "使用以下命令管理策略:"
        echo -e "  ${BLUE}查看日志:${NC} ./view_logs.sh"
        echo -e "  ${BLUE}停止策略:${NC} ./stop_trading.sh"
        echo -e "  ${BLUE}连接会话:${NC} screen -r $SCREEN_SESSION"
        echo -e "  ${BLUE}分离会话:${NC} Ctrl+A, D"
    else
        print_message $RED "策略启动失败"
        exit 1
    fi
}

# 显示启动信息
show_startup_info() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}           网格交易机器人 - 实盘启动脚本${NC}"
    echo "============================================================"
    echo -e "${BLUE}项目:${NC} $PROJECT_NAME"
    echo -e "${BLUE}脚本:${NC} $PYTHON_SCRIPT"
    echo -e "${BLUE}时间:${NC} $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    echo ""
}

# 主函数
main() {
    show_startup_info
    check_if_running
    check_dependencies
    install_dependencies
    start_strategy
    
    echo ""
    print_message $GREEN "网格交易策略已在后台启动完成!"
    print_message $YELLOW "重要提醒:"
    echo -e "  ${YELLOW}1. 请确保VPS网络稳定${NC}"
    echo -e "  ${YELLOW}2. 定期检查策略运行状态${NC}"
    echo -e "  ${YELLOW}3. 监控账户资金和风险${NC}"
    echo -e "  ${YELLOW}4. 停止策略时使用 ./stop_trading.sh${NC}"
    echo ""
}

# 执行主函数
main "$@"
