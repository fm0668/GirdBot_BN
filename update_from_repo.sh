#!/bin/bash

# =============================================================================
# 网格交易机器人 - VPS更新脚本
# 用于从GitHub仓库拉取最新代码更新
# =============================================================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ❌ $1${NC}"
}

log_step() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 $1${NC}"
}

# 检查是否在正确的目录
check_directory() {
    if [[ ! -f "grid_strategy.py" ]] || [[ ! -f "main.py" ]]; then
        log_error "错误：当前目录不是网格交易机器人项目目录"
        log_error "请确保在包含 grid_strategy.py 和 main.py 的目录中运行此脚本"
        exit 1
    fi
}

# 检查Git仓库状态
check_git_status() {
    if [[ ! -d ".git" ]]; then
        log_error "错误：当前目录不是Git仓库"
        exit 1
    fi
    
    # 检查是否有未提交的更改
    if ! git diff --quiet || ! git diff --cached --quiet; then
        log_warn "检测到本地有未提交的更改"
        echo
        git status --short
        echo
        read -p "是否要继续更新？这将覆盖本地更改 (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "更新已取消"
            exit 0
        fi
    fi
}

# 停止运行中的策略
stop_strategy() {
    log_step "检查并停止运行中的策略..."
    
    if [[ -f "stop_trading.sh" ]]; then
        # 检查是否有运行中的策略
        if pgrep -f "python.*main.py" > /dev/null; then
            log_warn "发现运行中的策略，正在停止..."
            echo "Y" | ./stop_trading.sh
            log_info "策略已停止"
        else
            log_info "没有运行中的策略"
        fi
    else
        log_warn "未找到 stop_trading.sh 脚本"
    fi
}

# 备份当前配置
backup_config() {
    log_step "备份当前配置文件..."
    
    # 备份配置文件
    if [[ -f "config.py" ]]; then
        cp config.py config.py.backup.$(date +%Y%m%d_%H%M%S)
        log_info "配置文件已备份"
    fi
    
    # 备份日志目录
    if [[ -d "log" ]]; then
        log_info "保留现有日志目录"
    fi
}

# 拉取最新代码
pull_updates() {
    log_step "从远程仓库拉取最新代码..."
    
    # 获取远程更新
    git fetch origin
    
    # 显示即将更新的内容
    echo
    log_info "即将应用的更新："
    git log --oneline HEAD..origin/main | head -5
    echo
    
    # 强制更新到最新版本
    git reset --hard origin/main
    
    log_info "代码更新完成"
}

# 恢复配置文件
restore_config() {
    log_step "恢复配置文件..."
    
    # 查找最新的备份配置文件
    latest_backup=$(ls -t config.py.backup.* 2>/dev/null | head -1)
    
    if [[ -n "$latest_backup" ]]; then
        log_info "发现备份配置文件: $latest_backup"
        read -p "是否要恢复备份的配置文件？(Y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            log_warn "跳过配置文件恢复，请手动检查 config.py"
        else
            cp "$latest_backup" config.py
            log_info "配置文件已恢复"
        fi
    else
        log_warn "未找到备份配置文件，请检查 config.py 设置"
    fi
}

# 检查依赖
check_dependencies() {
    log_step "检查Python依赖..."
    
    if [[ -f "requirements.txt" ]]; then
        pip install -r requirements.txt --quiet
        log_info "依赖检查完成"
    else
        log_warn "未找到 requirements.txt 文件"
    fi
}

# 验证更新
verify_update() {
    log_step "验证更新..."
    
    # 检查关键文件
    if [[ -f "grid_strategy.py" ]] && [[ -f "main.py" ]] && [[ -f "exchange_client.py" ]]; then
        log_info "关键文件检查通过"
    else
        log_error "关键文件缺失，更新可能失败"
        exit 1
    fi
    
    # 尝试导入检查
    if python3 -c "from grid_strategy import GridStrategy; print('✅ 导入检查通过')" 2>/dev/null; then
        log_info "代码语法检查通过"
    else
        log_error "代码语法检查失败，请检查更新"
        exit 1
    fi
}

# 显示更新摘要
show_summary() {
    echo
    echo "============================================================"
    log_info "更新完成摘要"
    echo "============================================================"
    
    # 显示当前版本信息
    echo "📍 当前版本："
    git log --oneline -1
    echo
    
    # 显示最近的更新
    echo "📝 最近5次更新："
    git log --oneline -5
    echo
    
    log_info "✅ 网格交易机器人已更新到最新版本"
    echo
    log_info "🚀 可以使用 ./start_live_trading.sh 启动策略"
    echo "============================================================"
}

# 主函数
main() {
    echo "============================================================"
    echo "           网格交易机器人 - VPS更新工具"
    echo "============================================================"
    echo
    
    # 执行更新流程
    check_directory
    check_git_status
    stop_strategy
    backup_config
    pull_updates
    restore_config
    check_dependencies
    verify_update
    show_summary
}

# 运行主函数
main "$@"
