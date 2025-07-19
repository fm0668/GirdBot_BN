# ==================== 配置文件模板 ====================
# 使用说明：
# 1. 复制此文件为 config.py
# 2. 填入你的API密钥和其他配置参数
# 3. config.py 已被添加到 .gitignore，不会被上传到GitHub

# ==================== API 配置 ====================
API_KEY = "your_api_key_here"  # 替换为你的 API Key
API_SECRET = "your_api_secret_here"  # 替换为你的 API Secret

# ==================== 交易配置 ====================
COIN_NAME = "DOGE"  # 交易币种
CONTRACT_TYPE = "USDC"  # 合约类型：USDT 或 USDC
GRID_SPACING = 0.001  # 网格间距 (0.1%)
INITIAL_QUANTITY = 20  # 初始交易数量 (币数量) - 确保订单价值大于5 USDC
LEVERAGE = 10  # 杠杆倍数

# ==================== WebSocket 配置 ====================
WEBSOCKET_URL = "wss://fstream.binance.com/ws"  # WebSocket URL

# ==================== 风控配置 ====================
POSITION_THRESHOLD = 500  # 锁仓阈值
POSITION_LIMIT = 100  # 持仓数量阈值
MAX_POSITION_RATIO = 0.8  # 最大仓位比例
STOP_LOSS_RATIO = 0.1     # 止损比例
VOLATILITY_WINDOW = 100   # 波动率计算窗口
MIN_GRID_SPACING = 0.0005 # 最小网格间距
MAX_GRID_SPACING = 0.005  # 最大网格间距

# ==================== 时间配置 ====================
SYNC_TIME = 10  # 同步时间（秒）
ORDER_FIRST_TIME = 10  # 首单间隔时间

# ==================== 对冲配置 ====================
ENABLE_HEDGE_INITIALIZATION = True  # 启用对冲初始化模式
HEDGE_INIT_DELAY = 1                 # 对冲初始化延迟（秒）- 确保双向同时开仓

# ==================== API频率控制配置 ====================
# 基于币安期货API限制计算的冷却时间
# fetch_open_orders权重: 单个交易对=1, 所有交易对=40
# 保守估计API限制: 1200 weight/分钟 = 20 weight/秒

ORDERS_SYNC_COOLDOWN = 3      # 标准订单同步冷却时间（秒）- 保守设置
FAST_SYNC_COOLDOWN = 1        # 快速市场订单同步冷却时间（秒）- 1秒=1weight，安全
PRICE_CHANGE_THRESHOLD = 0.002 # 价格变化阈值，超过此值认为是快速波动（0.2%）
FAST_MARKET_WINDOW = 10       # 快速市场检测窗口时间（秒）

# API限制相关配置
API_WEIGHT_LIMIT_PER_MINUTE = 1200  # 每分钟权重限制（保守估计）
FETCH_ORDERS_WEIGHT = 1              # fetch_open_orders单个交易对权重
SAFETY_MARGIN = 0.8                  # 安全边际，只使用80%的限制
