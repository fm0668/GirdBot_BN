#!/bin/bash

# =============================================================================
# 网格交易机器人 - 优雅停止脚本
# =============================================================================
# 功能：安全停止策略并清理持仓
# 使用：./stop_trading.sh [选项]
# =============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
PID_FILE="grid_bot.pid"
SCREEN_SESSION="grid_trading"
CLEANUP_SCRIPT="test_cleanup.py"

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] ${message}${NC}"
}

# 检查策略是否运行
check_if_running() {
    if [ ! -f "$PID_FILE" ]; then
        print_message $YELLOW "策略未运行 (未找到PID文件)"
        return 1
    fi
    
    local pid=$(cat "$PID_FILE")
    if ! ps -p "$pid" > /dev/null 2>&1; then
        print_message $YELLOW "策略未运行 (进程不存在)"
        rm -f "$PID_FILE"
        return 1
    fi
    
    print_message $BLUE "发现运行中的策略 (PID: $pid)"
    return 0
}

# 发送停止信号
send_stop_signal() {
    local pid=$(cat "$PID_FILE")
    print_message $BLUE "发送停止信号到进程 $pid..."
    
    # 首先尝试优雅停止 (SIGTERM)
    kill -TERM "$pid" 2>/dev/null
    
    # 等待进程优雅退出
    local count=0
    while [ $count -lt 30 ]; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            print_message $GREEN "策略已优雅停止"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
        count=$((count + 1))
        if [ $((count % 5)) -eq 0 ]; then
            print_message $YELLOW "等待策略停止... ($count/30秒)"
        fi
    done
    
    # 如果优雅停止失败，强制停止
    print_message $YELLOW "优雅停止超时，尝试强制停止..."
    kill -KILL "$pid" 2>/dev/null
    sleep 2
    
    if ! ps -p "$pid" > /dev/null 2>&1; then
        print_message $GREEN "策略已强制停止"
        rm -f "$PID_FILE"
        return 0
    else
        print_message $RED "无法停止策略进程"
        return 1
    fi
}

# 停止screen会话
stop_screen_session() {
    if screen -list | grep -q "$SCREEN_SESSION"; then
        print_message $BLUE "停止Screen会话: $SCREEN_SESSION"
        screen -S "$SCREEN_SESSION" -X quit 2>/dev/null
        sleep 1
        
        if ! screen -list | grep -q "$SCREEN_SESSION"; then
            print_message $GREEN "Screen会话已停止"
        else
            print_message $YELLOW "Screen会话可能仍在运行"
        fi
    fi
}

# 执行清理操作
execute_cleanup() {
    print_message $BLUE "开始执行账户清理..."
    
    if [ -f "$CLEANUP_SCRIPT" ]; then
        print_message $BLUE "使用清理脚本: $CLEANUP_SCRIPT"
        
        # 自动选择完整清理功能
        echo "1" | python3 "$CLEANUP_SCRIPT"
        local cleanup_result=$?
        
        if [ $cleanup_result -eq 0 ]; then
            print_message $GREEN "账户清理完成"
        else
            print_message $YELLOW "清理脚本执行完成，请检查结果"
        fi
    else
        print_message $YELLOW "未找到清理脚本 $CLEANUP_SCRIPT"
        print_message $YELLOW "请手动检查并清理账户中的挂单和持仓"
    fi
}

# 显示停止前状态
show_pre_stop_status() {
    echo ""
    echo "============================================================"
    echo -e "${BLUE}              策略停止前状态检查${NC}"
    echo "============================================================"
    
    # 显示最新的账户和持仓信息
    local latest_log=$(ls -t log/grid_bot_*.log 2>/dev/null | head -1)
    if [ -n "$latest_log" ] && [ -f "$latest_log" ]; then
        print_message $BLUE "最新账户信息:"
        local latest_balance=$(grep "账户数据更新" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$latest_balance" ]; then
            echo "  $latest_balance"
        fi
        
        print_message $BLUE "最新持仓信息:"
        local latest_position=$(grep "持仓数据更新" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$latest_position" ]; then
            echo "  $latest_position"
        fi
        
        # 统计当前挂单
        local recent_orders=$(grep "同步 orders" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$recent_orders" ]; then
            print_message $BLUE "最新挂单状态:"
            echo "  $recent_orders"
        fi
    fi
    echo ""
}

# 确认停止操作
confirm_stop() {
    local force_mode=$1
    
    if [ "$force_mode" = "force" ]; then
        return 0
    fi
    
    echo -e "${YELLOW}⚠️  即将停止网格交易策略并清理账户${NC}"
    echo -e "${YELLOW}   这将撤销所有挂单并平仓所有持仓${NC}"
    echo ""
    read -p "确认继续? (y/N): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_message $BLUE "操作已取消"
        exit 0
    fi
}

# 显示帮助信息
show_help() {
    echo "============================================================"
    echo -e "${BLUE}           网格交易机器人 - 停止脚本${NC}"
    echo "============================================================"
    echo ""
    echo "使用方法:"
    echo "  ./stop_trading.sh [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示帮助信息"
    echo "  -f, --force    强制停止，不询问确认"
    echo "  -n, --no-cleanup  只停止策略，不执行清理"
    echo ""
    echo "功能:"
    echo "  1. 优雅停止策略进程"
    echo "  2. 关闭Screen会话"
    echo "  3. 清理所有挂单和持仓"
    echo "  4. 清理PID文件"
    echo ""
    echo "示例:"
    echo "  ./stop_trading.sh        # 正常停止"
    echo "  ./stop_trading.sh -f     # 强制停止"
    echo "  ./stop_trading.sh -n     # 只停止不清理"
    echo ""
}

# 主函数
main() {
    local force_mode=""
    local no_cleanup=""
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -f|--force)
                force_mode="force"
                shift
                ;;
            -n|--no-cleanup)
                no_cleanup="true"
                shift
                ;;
            *)
                print_message $RED "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    echo ""
    echo "============================================================"
    echo -e "${RED}           网格交易机器人 - 优雅停止${NC}"
    echo "============================================================"
    echo ""
    
    # 检查是否运行
    if ! check_if_running; then
        if [ "$no_cleanup" != "true" ]; then
            print_message $BLUE "策略未运行，但仍可执行清理操作"
            confirm_stop "$force_mode"
            execute_cleanup
        fi
        exit 0
    fi
    
    # 显示停止前状态
    show_pre_stop_status
    
    # 确认停止
    confirm_stop "$force_mode"
    
    # 停止策略
    print_message $BLUE "开始停止网格交易策略..."
    
    if send_stop_signal; then
        stop_screen_session
        
        if [ "$no_cleanup" != "true" ]; then
            echo ""
            execute_cleanup
        fi
        
        echo ""
        print_message $GREEN "网格交易策略已安全停止"
        
        if [ "$no_cleanup" = "true" ]; then
            print_message $YELLOW "注意: 未执行清理操作，请手动检查账户状态"
        fi
        
    else
        print_message $RED "停止策略失败"
        exit 1
    fi
    
    echo ""
    print_message $BLUE "停止操作完成"
}

# 执行主函数
main "$@"
