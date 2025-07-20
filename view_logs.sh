#!/bin/bash

# =============================================================================
# 网格交易机器人 - 日志查看脚本
# =============================================================================
# 功能：查看策略运行状况、交易情况、账户状态等重要信息
# 使用：./view_logs.sh [选项]
# =============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# 配置
LOG_DIR="log"
PID_FILE="grid_bot.pid"
SCREEN_SESSION="grid_trading"

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] ${message}${NC}"
}

# 检查策略是否运行
check_strategy_status() {
    echo "============================================================"
    echo -e "${CYAN}                策略运行状态检查${NC}"
    echo "============================================================"
    
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            print_message $GREEN "策略正在运行 (PID: $pid)"
            
            # 检查screen会话
            if screen -list | grep -q "$SCREEN_SESSION"; then
                print_message $GREEN "Screen会话活跃: $SCREEN_SESSION"
            else
                print_message $YELLOW "Screen会话未找到"
            fi
            
            # 显示运行时间
            local start_time=$(ps -o lstart= -p "$pid" 2>/dev/null)
            if [ -n "$start_time" ]; then
                print_message $BLUE "启动时间: $start_time"
            fi
            
        else
            print_message $RED "策略未运行 (PID文件存在但进程不存在)"
            rm -f "$PID_FILE"
        fi
    else
        print_message $RED "策略未运行 (未找到PID文件)"
    fi
    echo ""
}

# 显示最新日志
show_recent_logs() {
    echo "============================================================"
    echo -e "${CYAN}                最新运行日志${NC}"
    echo "============================================================"
    
    # 查找最新的日志文件
    local latest_log=$(ls -t $LOG_DIR/grid_bot_*.log 2>/dev/null | head -1)
    
    if [ -n "$latest_log" ] && [ -f "$latest_log" ]; then
        print_message $BLUE "日志文件: $latest_log"
        echo ""
        
        # 显示最后50行日志
        tail -50 "$latest_log" | while IFS= read -r line; do
            # 根据日志级别着色
            if [[ $line == *"ERROR"* ]]; then
                echo -e "${RED}$line${NC}"
            elif [[ $line == *"WARNING"* ]]; then
                echo -e "${YELLOW}$line${NC}"
            elif [[ $line == *"INFO"* ]]; then
                if [[ $line == *"下单成功"* ]] || [[ $line == *"成交"* ]]; then
                    echo -e "${GREEN}$line${NC}"
                elif [[ $line == *"账户"* ]] || [[ $line == *"余额"* ]] || [[ $line == *"盈亏"* ]]; then
                    echo -e "${CYAN}$line${NC}"
                elif [[ $line == *"持仓"* ]] || [[ $line == *"订单"* ]]; then
                    echo -e "${PURPLE}$line${NC}"
                else
                    echo "$line"
                fi
            else
                echo "$line"
            fi
        done
    else
        print_message $RED "未找到日志文件"
    fi
    echo ""
}

# 显示交易统计
show_trading_stats() {
    echo "============================================================"
    echo -e "${CYAN}                交易统计信息${NC}"
    echo "============================================================"
    
    local latest_log=$(ls -t $LOG_DIR/grid_bot_*.log 2>/dev/null | head -1)
    
    if [ -n "$latest_log" ] && [ -f "$latest_log" ]; then
        # 统计订单数量
        local buy_orders=$(grep -c "下单成功.*buy" "$latest_log" 2>/dev/null || echo "0")
        local sell_orders=$(grep -c "下单成功.*sell" "$latest_log" 2>/dev/null || echo "0")
        local total_orders=$((buy_orders + sell_orders))
        
        # 统计撤单数量
        local cancelled_orders=$(grep -c "撤销挂单成功" "$latest_log" 2>/dev/null || echo "0")
        
        # 统计错误数量
        local errors=$(grep -c "ERROR" "$latest_log" 2>/dev/null || echo "0")
        local warnings=$(grep -c "WARNING" "$latest_log" 2>/dev/null || echo "0")
        
        echo -e "${BLUE}📊 订单统计:${NC}"
        echo -e "  买单数量: ${GREEN}$buy_orders${NC}"
        echo -e "  卖单数量: ${GREEN}$sell_orders${NC}"
        echo -e "  总订单数: ${GREEN}$total_orders${NC}"
        echo -e "  撤单数量: ${YELLOW}$cancelled_orders${NC}"
        echo ""
        
        echo -e "${BLUE}⚠️  异常统计:${NC}"
        echo -e "  错误数量: ${RED}$errors${NC}"
        echo -e "  警告数量: ${YELLOW}$warnings${NC}"
        echo ""
        
        # 显示最新的账户信息
        echo -e "${BLUE}💰 最新账户信息:${NC}"
        local latest_balance=$(grep "账户数据更新" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$latest_balance" ]; then
            echo -e "  ${CYAN}$latest_balance${NC}"
        else
            echo -e "  ${YELLOW}未找到账户信息${NC}"
        fi
        
        # 显示最新的持仓信息
        local latest_position=$(grep "持仓数据更新" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$latest_position" ]; then
            echo -e "  ${PURPLE}$latest_position${NC}"
        fi
        
        # 显示最新的杠杆优化计算
        local latest_leverage=$(grep "杠杆优化计算" "$latest_log" | tail -1 2>/dev/null)
        if [ -n "$latest_leverage" ]; then
            echo -e "  ${GREEN}$latest_leverage${NC}"
        fi
        
    else
        print_message $RED "无法读取日志文件进行统计"
    fi
    echo ""
}

# 实时监控模式
real_time_monitor() {
    echo "============================================================"
    echo -e "${CYAN}              实时日志监控模式${NC}"
    echo -e "${YELLOW}按 Ctrl+C 退出监控${NC}"
    echo "============================================================"
    
    local latest_log=$(ls -t $LOG_DIR/grid_bot_*.log 2>/dev/null | head -1)
    
    if [ -n "$latest_log" ] && [ -f "$latest_log" ]; then
        tail -f "$latest_log" | while IFS= read -r line; do
            # 根据内容着色显示
            if [[ $line == *"ERROR"* ]]; then
                echo -e "${RED}$line${NC}"
            elif [[ $line == *"WARNING"* ]]; then
                echo -e "${YELLOW}$line${NC}"
            elif [[ $line == *"下单成功"* ]] || [[ $line == *"成交"* ]]; then
                echo -e "${GREEN}$line${NC}"
            elif [[ $line == *"账户"* ]] || [[ $line == *"余额"* ]] || [[ $line == *"盈亏"* ]]; then
                echo -e "${CYAN}$line${NC}"
            elif [[ $line == *"持仓"* ]] || [[ $line == *"订单"* ]]; then
                echo -e "${PURPLE}$line${NC}"
            else
                echo "$line"
            fi
        done
    else
        print_message $RED "未找到日志文件"
    fi
}

# 显示帮助信息
show_help() {
    echo "============================================================"
    echo -e "${CYAN}           网格交易机器人 - 日志查看工具${NC}"
    echo "============================================================"
    echo ""
    echo "使用方法:"
    echo "  ./view_logs.sh [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示帮助信息"
    echo "  -s, --status   只显示策略状态"
    echo "  -l, --logs     只显示最新日志"
    echo "  -t, --stats    只显示交易统计"
    echo "  -m, --monitor  实时监控模式"
    echo "  -a, --all      显示所有信息 (默认)"
    echo ""
    echo "示例:"
    echo "  ./view_logs.sh           # 显示所有信息"
    echo "  ./view_logs.sh -m        # 实时监控"
    echo "  ./view_logs.sh -s        # 只看状态"
    echo ""
}

# 主函数
main() {
    case "${1:-all}" in
        -h|--help)
            show_help
            ;;
        -s|--status)
            check_strategy_status
            ;;
        -l|--logs)
            show_recent_logs
            ;;
        -t|--stats)
            show_trading_stats
            ;;
        -m|--monitor)
            real_time_monitor
            ;;
        -a|--all|*)
            check_strategy_status
            show_trading_stats
            show_recent_logs
            echo -e "${BLUE}提示: 使用 './view_logs.sh -m' 进入实时监控模式${NC}"
            ;;
    esac
}

# 执行主函数
main "$@"
