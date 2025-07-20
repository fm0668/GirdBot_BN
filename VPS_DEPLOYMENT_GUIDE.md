# 网格交易机器人 VPS 部署指南

## 📋 目录
- [系统要求](#系统要求)
- [VPS选择建议](#vps选择建议)
- [环境准备](#环境准备)
- [项目部署](#项目部署)
- [配置设置](#配置设置)
- [启动策略](#启动策略)
- [监控管理](#监控管理)
- [安全建议](#安全建议)
- [故障排除](#故障排除)

## 🖥️ 系统要求

### 最低配置
- **CPU**: 1核心
- **内存**: 1GB RAM
- **存储**: 10GB SSD
- **网络**: 稳定的互联网连接
- **系统**: Ubuntu 20.04+ / CentOS 8+ / Debian 11+

### 推荐配置
- **CPU**: 2核心
- **内存**: 2GB RAM
- **存储**: 20GB SSD
- **网络**: 低延迟连接 (<100ms到交易所)
- **系统**: Ubuntu 22.04 LTS

## 🌐 VPS选择建议

### 推荐VPS提供商
1. **Vultr** - 性价比高，全球节点
2. **DigitalOcean** - 稳定可靠，文档完善
3. **Linode** - 性能优秀，技术支持好
4. **AWS EC2** - 企业级，可扩展性强
5. **阿里云/腾讯云** - 国内用户友好

### 地理位置选择
- **亚洲用户**: 新加坡、东京、香港
- **欧洲用户**: 伦敦、法兰克福、阿姆斯特丹
- **美洲用户**: 纽约、旧金山、多伦多

## 🔧 环境准备

### 1. 连接VPS
```bash
# 使用SSH连接VPS
ssh root@your_vps_ip

# 或使用密钥连接
ssh -i your_key.pem root@your_vps_ip
```

### 2. 更新系统
```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y

# CentOS/RHEL
sudo yum update -y
```

### 3. 安装必要软件
```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-pip git screen curl wget

# CentOS/RHEL
sudo yum install -y python3 python3-pip git screen curl wget
```

### 4. 配置时区
```bash
# 设置时区为UTC (推荐)
sudo timedatectl set-timezone UTC

# 或设置为本地时区
sudo timedatectl set-timezone Asia/Shanghai
```

## 📦 项目部署

### 1. 克隆项目
```bash
# 克隆项目到VPS
git clone https://github.com/fm0668/GirdBot_BN.git
cd GirdBot_BN
```

### 2. 安装Python依赖
```bash
# 安装依赖包
pip3 install -r requirements.txt

# 验证安装
python3 -c "import ccxt, websockets, numpy; print('依赖安装成功')"
```

### 3. 设置执行权限
```bash
# 给脚本添加执行权限
chmod +x start_live_trading.sh
chmod +x view_logs.sh
chmod +x stop_trading.sh
```

## ⚙️ 配置设置

### 1. 配置API密钥
```bash
# 编辑配置文件
nano config.py

# 或使用vim
vim config.py
```

**重要配置项**:
```python
# API配置 (必须修改)
API_KEY = "your_binance_api_key"
API_SECRET = "your_binance_api_secret"

# 交易配置
COIN_NAME = "DOGE"              # 交易币种
CONTRACT_TYPE = "USDC"          # 合约类型
LEVERAGE = 20                   # 杠杆倍数
GRID_SPACING = 0.001           # 网格间距

# 杠杆优化配置
LEVERAGE_BASED_CALCULATION = True
LEVERAGE_ORDER_RATIO = 0.04    # 4%资金使用比例
```

### 2. 测试配置
```bash
# 测试API连接
python3 -c "
from exchange_client import ExchangeClient
client = ExchangeClient('API_KEY', 'API_SECRET', 'DOGE', 'USDC')
print('API连接测试成功')
"
```

## 🚀 启动策略

### 1. 启动网格交易
```bash
# 启动策略 (后台运行)
./start_live_trading.sh
```

### 2. 验证启动
```bash
# 检查策略状态
./view_logs.sh -s

# 查看实时日志
./view_logs.sh -m
```

## 📊 监控管理

### 1. 查看策略状态
```bash
# 查看完整状态
./view_logs.sh

# 只看运行状态
./view_logs.sh -s

# 只看交易统计
./view_logs.sh -t

# 实时监控
./view_logs.sh -m
```

### 2. 连接Screen会话
```bash
# 连接到策略会话
screen -r grid_trading

# 分离会话 (在screen内按键)
Ctrl+A, D
```

### 3. 手动检查
```bash
# 检查进程
ps aux | grep python3

# 检查网络连接
netstat -an | grep ESTABLISHED

# 检查磁盘空间
df -h

# 检查内存使用
free -h
```

## 🛑 停止策略

### 1. 优雅停止
```bash
# 正常停止 (会清理持仓)
./stop_trading.sh

# 强制停止
./stop_trading.sh -f

# 只停止不清理
./stop_trading.sh -n
```

### 2. 紧急停止
```bash
# 如果脚本无法停止，手动处理
pkill -f start_grid_bot.py
screen -S grid_trading -X quit
```

## 🔒 安全建议

### 1. 防火墙配置
```bash
# Ubuntu UFW
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 22

# CentOS firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload
```

### 2. SSH安全
```bash
# 修改SSH配置
sudo nano /etc/ssh/sshd_config

# 建议修改:
# Port 2222                    # 修改默认端口
# PermitRootLogin no           # 禁止root登录
# PasswordAuthentication no    # 禁用密码登录
# PubkeyAuthentication yes     # 启用密钥登录

# 重启SSH服务
sudo systemctl restart sshd
```

### 3. API密钥安全
- ✅ 只给必要的权限 (现货/期货交易)
- ✅ 限制IP白名单
- ❌ 不要给提现权限
- ❌ 不要在公共场所配置

### 4. 定期备份
```bash
# 创建备份脚本
cat > backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf "gridbot_backup_$DATE.tar.gz" \
    config.py log/ *.py *.sh *.md
echo "备份完成: gridbot_backup_$DATE.tar.gz"
EOF

chmod +x backup.sh
```

## 🔧 故障排除

### 常见问题

#### 1. 策略无法启动
```bash
# 检查Python环境
python3 --version
pip3 list | grep ccxt

# 检查配置文件
python3 -c "import config; print('配置文件正常')"

# 查看详细错误
python3 start_grid_bot.py
```

#### 2. API连接失败
```bash
# 测试网络连接
ping api.binance.com
curl -I https://fapi.binance.com/fapi/v1/ping

# 检查API密钥
python3 test_cleanup.py
```

#### 3. 内存不足
```bash
# 检查内存使用
free -h
top -p $(pgrep python3)

# 清理日志文件
find log/ -name "*.log" -mtime +7 -delete
```

#### 4. 磁盘空间不足
```bash
# 检查磁盘使用
df -h
du -sh log/

# 清理旧日志
find log/ -name "*.log" -mtime +3 -delete
```

### 日志分析
```bash
# 查看错误日志
grep -i error log/grid_bot_*.log | tail -20

# 查看警告信息
grep -i warning log/grid_bot_*.log | tail -20

# 统计交易次数
grep "下单成功" log/grid_bot_*.log | wc -l
```

## 📞 技术支持

### 获取帮助
1. **查看日志**: `./view_logs.sh`
2. **检查状态**: `./view_logs.sh -s`
3. **GitHub Issues**: 提交问题到项目仓库
4. **社区讨论**: 参与项目讨论

### 性能优化
1. **选择低延迟VPS**
2. **定期清理日志文件**
3. **监控系统资源使用**
4. **优化网络连接**

---

## ⚠️ 免责声明

- 本软件仅供学习和研究使用
- 量化交易存在风险，请谨慎使用
- 使用前请充分测试和验证
- 作者不承担任何交易损失责任

---

**祝您交易顺利！** 🚀
